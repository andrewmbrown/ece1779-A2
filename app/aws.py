import boto3
import json
import time
from datetime import datetime, timedelta
from access import access_keys
# initialize the boto3 stuff here universally

class AwsClient:
    def __init__(self) -> None:
        # User Dependent Values
        self.AWS_ACC_KEY = access_keys['AWS_ACC_KEY']
        self.AWS_SEC_KEY = access_keys['AWS_SECRET_KEY']
        self.keypair_name ='ece1779-a2-ec2-key'
        self.security_group=['sg-0e1f1e5bb640b7d1a']
        self.target_group_arn = 'arn:aws:elasticloadbalancing:us-east-1:322026937675:targetgroup/lb-1779-5000/4e14bc1d4bdc93e0'
        self.loadbalancer_arn_cloudwatch = 'app/lb-1779-5000/c35ba0a409be6527'
        self.s3_bucket_name = 'ece1779a2g82'
        self.WORKER_MAXIMUM = 6
        self.WORKER_MINIMUM = 1

        # Universally Constant Values
        session = boto3.Session(
                aws_access_key_id=self.AWS_ACC_KEY,
                aws_secret_access_key=self.AWS_SEC_KEY)
        self.ec2 = boto3.client('ec2',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY, 
                region_name="us-east-1")
        self.ec2resource = session.resource('ec2', region_name='us-east-1')
        self.elb = boto3.client('elbv2',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY, 
                region_name="us-east-1")
        self.cloudwatch = boto3.client('cloudwatch',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY, 
                region_name="us-east-1")
        self.s3 = session.resource('s3', region_name='us-east-1')
        self.rds = boto3.client('rds',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY,  
                region_name='us-east-1')
        self.AMI_IMAGE_ID = "ami-04942f15a25e561c7"
        self.instance_type ='t2.micro'
        self.monitoring = {
            'Enabled': True
        }
        self.autoscaler_state = False


    def WAIT_startup_complete(self, worker_id):
        '''
        function that waits for the EC2 startup to complete

        needed because EC2 inst can only be added to target group 
        when state is RUNNING and NOT PENDING 

        continuously checks state every 5 seconds until returns True
        '''
        r = self.ec2.describe_instance_status(InstanceIds=[worker_id])
        while len(r['InstanceStatuses']) == 0:
            time.sleep(5)
            r = self.ec2.describe_instance_status(InstanceIds=[worker_id])
        while r['InstanceStatuses'][0]['InstanceState']['Name'] != 'running':
            time.sleep(5)
            r = self.ec2.describe_instance_status(InstanceIds=[worker_id])
        time.sleep(5)
        return True 

    def ELB_filter_instances_by_ami(self): # DONE
        '''
        gets all workers filtered by AMI
        keeps track of all active workers
        used by the worker target status function to get untagged but stopped functions

        returns list of workers with the self.AMI_IMAGE_ID image with following structure:
            {
                'id' -> EC2 id 
                'state' -> EC2 state 
            }
        '''
        r = self.ec2.describe_instances()
        rr = r['Reservations']
        rel_wk = [rr[i] for i in range(len(rr)) if rr[i]['Instances'][0]['ImageId'] == self.AMI_IMAGE_ID]
        # rel_wk[0].keys() = [Groups, Instances, OwnerId, ReservationId]
        # if terminated, smaller size instance package than if running
        wk_i_data = [rel_wk[i]['Instances'][0] for i in range(len(rel_wk))]
        worker_data_filtered = [{'id': wk_i_data[u]['InstanceId'], 'state': wk_i_data[u]['State']['Name']} for u in range(len(wk_i_data))]
        return worker_data_filtered

    def ELB_worker_target_status(self, get_all_targeted=True, get_active_targets=False, get_untargeted=False): # DONE
        '''
        function that checks the status of EC2 workers and targets
        three input argument variants:
        (True, False, False) -> get all currently targeted workers
        (False, True, False) -> get all non-draining targeted workers
        (False, False, True) -> get all workers not in the target group (implied stopped)

        returns the list of workers for each combination in the following format:
            {
                id -> EC2 instance id
                health -> target group health status
            }
        '''
        elb_r = self.elb.describe_target_health(TargetGroupArn=self.target_group_arn)
        workers = []
        target_worker_ids = []
        elb_r_health = elb_r["TargetHealthDescriptions"]
        for target_worker in elb_r_health:
            # grabs all workers
            t_w_id = target_worker['Target']['Id']
            t_w_health = target_worker['TargetHealth']['State']
            workers.append({'id': t_w_id, 'health': t_w_health})
            target_worker_ids.append(t_w_id)

        if get_all_targeted:
            # get all healthy, unhealthy, draining, etc. workers 
            return workers 
        elif get_active_targets: 
            # filters to only return non draining workers i.e. ones in the targ group
            # workers_not_draining = [worker['health'] != 'draining' for worker in workers]
            workers_active = [worker for worker in workers if worker['health'] != 'draining'] # TODO: test this
            return workers_active
        elif get_untargeted:
            all_workers_by_ami = self.ELB_filter_instances_by_ami()
            non_targeted_workers = [worker for worker in all_workers_by_ami if worker['id'] not in target_worker_ids]
            return non_targeted_workers
        else:
            return []

    def EC2_get_stopped_workers(self):
        '''
        gets all stopped workers via (False, False, True) command on worker target status (see docstring)
        returns list of workers with worker target status function dict format but state stopped 
        '''
        untargeted_workers = self.ELB_worker_target_status(get_all_targeted=False, get_active_targets=False, get_untargeted=True)
        stopped_workers = [worker for worker in untargeted_workers if worker['state'] == 'stopped']
        return stopped_workers

    def EC2_create_worker(self): # DONE
        '''
        CREATES A WORKER via boto3

        SEE BELOW for the documentation
        https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.run_instances
        r format: dict with keys:
            Groups
            Instances = list with one object at idx 0, a dict with keys:
                AmiLaunchIndex
                ImageId -> ID of the AMI
                InstanceId -> ID of the EC2 instance 
                InstanceType -> t2.micro
                KeyName -> key name for the key pair 
                LaunchTime -> datetime giving launch time 
                Monitoring -> {'State': 'pending', 'running', etc.}
                ...
                State -> {'Code': 0, 'name': 'pending'}

            OwnerId
            ReservationId
            ResponseMetadata
            ...
        
        returns 
            {
                response -> the full boto3 ec2 run instances response dict
                worker -> worker dict format
                FAILED -> 0 if good -1 if failed
            }
        '''
        try:
            r = self.ec2.run_instances(
                ImageId=self.AMI_IMAGE_ID,
                MinCount=1,
                MaxCount=1,
                InstanceType=self.instance_type,
                KeyName=self.keypair_name,
                SecurityGroupIds=self.security_group, 
                Monitoring=self.monitoring
            )
            worker = {
                'id': r['Instances'][0]['InstanceId'],
                'launchtime': r['Instances'][0]['LaunchTime'],
                'monitoring': r['Instances'][0]['Monitoring'],
                'state': r['Instances'][0]['State']
            }
            # print("Created worker: {}".format(worker['id']))
            return {'response': r, 'worker': worker, 'FAILED': 0}
        except:
            # print("Unable to create worker!")
            return {'response': None, 'worker': None, 'FAILED': -1}

    def EC2_increase_workers(self, ratio=False, amount=2.0):
        '''
        worker increase function

        clicking button on manager app -> ratio False, amount ignored
        checks to see if any prev stopped workers, if so starts one
        else creates one from scratch
        uses wait function to wait for state to go pending -> running
        then registers to target

        autoscaler uses ratio and amount
        based on policy, then recurses into non-ratio version in loop by ratio calc

        return 200 if successful else -1 
        '''
        # ratio=False, amount ignored as just 1; ratio=True, amount used
        if not ratio:
            # increase by 1

            w_id = None
            stopped_workers = self.EC2_get_stopped_workers()
            if len(stopped_workers) > 0:
                w_id = stopped_workers[0]['id']
                self.ec2.start_instances(InstanceIds=[w_id])
            else:
                r = self.EC2_create_worker()
                if r['FAILED'] == -1:
                    # print("ERROR: Could not increase workers!")
                    return -1
                w_id = r['worker']['id']

            self.WAIT_startup_complete(w_id) # wait on the startup to complete

            r_elb = self.elb.register_targets(TargetGroupArn=self.target_group_arn, Targets=[{'Id': w_id, 'Port':5000}])
            if r_elb:
                if 'ResponseMetadata' in r_elb:
                    if 'HTTPStatusCode' in r_elb['ResponseMetadata']:
                        HTTP_code = r_elb['ResponseMetadata']['HTTPStatusCode']
                        return HTTP_code
            return -1 
        else:
            if amount < 1:
                # print("Please use a ratio > 1 to grow")
                return []
            active_workers = self.ELB_worker_target_status(False, True, False)
            extra_workers = int(len(active_workers) * amount)
            num_new_workers = int(extra_workers - len(active_workers))
            if num_new_workers + len(active_workers) > self.WORKER_MAXIMUM:
                num_new_workers = self.WORKER_MAXIMUM - len(active_workers)
            created_workers = [self.EC2_increase_workers(ratio=False) for i in range(num_new_workers)]
            return created_workers

    def EC2_decrease_workers(self, ratio=False, amount=0.5):
        '''
        worker decrease function

        clicking button on manager app -> ratio False, amount ignored
        checks to see if any prev stopped workers, if so starts one
        else creates one from scratch
        uses wait function to wait for state to go pending -> running
        then registers to target

        autoscaler uses ratio and amount
        based on policy, then recurses into non-ratio version in loop by ratio calc

        return 200 if successful else -1 
        '''
        # ratio=False, amount ignored as just 1; ratio=True, amount used
        DEREG_HTTP_code = -1
        STOP_HTTP_code = -1
        if not ratio:
            active_workers = self.ELB_worker_target_status(get_all_targeted=False, get_active_targets=True, get_untargeted=False)
            if len(active_workers) == 0:
                # print("No workers active")
                return -1
            else:
                w_id = active_workers[0]['id'] # deregister and stop this worker 
                # deregister worker
                r_elb = self.elb.deregister_targets(TargetGroupArn=self.target_group_arn, Targets=[{'Id': w_id}])
                if r_elb:
                    if 'ResponseMetadata' in r_elb:
                        if 'HTTPStatusCode' in r_elb['ResponseMetadata']:
                            DEREG_HTTP_code = r_elb['ResponseMetadata']['HTTPStatusCode']
                if int(DEREG_HTTP_code) != 200:
                    return -1
                else: 
                    r_ec2 = self.ec2.stop_instances(InstanceIds=[w_id])
                    if r_elb:
                        if 'ResponseMetadata' in r_elb:
                            if 'HTTPStatusCode' in r_elb['ResponseMetadata']:
                                STOP_HTTP_code = r_elb['ResponseMetadata']['HTTPStatusCode']
                    if int(STOP_HTTP_code) != 200:
                        return -1
                    else:
                        return 200 # HTTP OK, EVERYTHING STOPPED FINE
        else:
            if amount > 1:
                # print("Please use a ratio < 1 to shrink")
                return []
            active_workers = self.ELB_worker_target_status(False, True, False)
            amount = 1 - amount 
            # correct amount to reduce e.g. reduce 4 by 0.75 -> 4 x 0.25 = 1 so 1 worker must be left
            # so 4 x 0.25 = 1, and num_worker_shutdown = 4 - 1 = 3
            extra_workers = int(len(active_workers) * amount)
            num_worker_shutdown = int(len(active_workers) - extra_workers)
            if len(active_workers) - num_worker_shutdown < self.WORKER_MINIMUM:
                num_worker_shutdown = len(active_workers) - self.WORKER_MINIMUM 
            stopped_workers = [self.EC2_decrease_workers(ratio=False) for i in range(num_worker_shutdown)]
            return stopped_workers


    def EC2_terminate_all_workers(self):
        # first stop all active workers
        while True:
            try:
                all_workers_stopped = self.EC2_decrease_workers()
                time.sleep(10)
                if all_workers_stopped == -1: break
            except:
                # print("not able to terminate all workers")
                return -1
        # now terminate all stopped workers
        try:
            # Incredibly dangerous line, terminates EVERY ec2, this would include the manager app itself if hosted on aws ec2
            self.ec2resource.instances.terminate()
        except:
            # print("termination failed")
            return -1
        return 200


    def S3_rds_delete_all_data(self):
        # function to delete all s3 and rds data
        # first s3
        try:
            bucket = self.s3.Bucket(self.s3_bucket_name)
            bucket.objects.all().delete()
        except:
            return -1

        # second rds
        try:
            snapshot_name = self.rds.describe_db_snapshots()
            response = self.rds.delete_db_snapshot(DBSnapshotIdentifier=snapshot_name)
        except:
            return -1
        return 200


    def Cloudwatch_CPU_usage_metrics(self, worker_id, start_s, end_s):
        '''
        gets cloudwatch cpu metrics
        '''
        r = self.cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPU_Util',
            Dimensions=[{'Name':'Instance_Id', 'Value':worker_id}],
            StartTime=start_s,
            EndTime=end_s,
            Period=60,
            Statistics=['Maximum'],
            Unit='Percent'
        )
        # print("response:")
        # print(r)
        if 'Datapoints' in r:
            datapoints = []
            for dp in r['Datapoints']:
                datapoints.append([
                    int(dp['Timestamp'].timestamp() * 1000),
                    float(dp['Maximum'])
                ])
            # print("full datapoints:")
            # print(datapoints)
            return json.dumps(sorted(datapoints, key=lambda x: x[0]))
        return json.dumps([[]])


    def Worker_Cloudwatch_CpuUtil(self):
        '''
        gets cloudwatch cpu metrics for workers
        '''
        metric_name = 'CPUUtilization'  # cloudwatch monitoring CPU
        stats = 'Average'

        CPU_Util = {}

        ec2_instances = self.ec2resource.instances.filter(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
            
        for instance in ec2_instances:
            # CPU Util metrics
            time_stamps = []
            cpu_stats = []
            response = self.cloudwatch.get_metric_statistics(
                Period=1 * 60,
                StartTime=datetime.utcnow() - timedelta(seconds=30 * 60),
                EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
                MetricName=metric_name,
                Namespace='AWS/EC2',
                Statistics=[stats],
                Dimensions=[{'Name': 'InstanceId', 'Value': instance.id},]
            )

            for point in response['Datapoints']:
                hour = point['Timestamp'].hour
                minute = point['Timestamp'].minute
                time = hour + minute/60
                time_stamps.append(round(time, 2))
                cpu_stats.append(round(point['Average'], 2))
            indexes = list(range(len(time_stamps)))
            indexes.sort(key=time_stamps.__getitem__)
            time_stamps = list(map(time_stamps.__getitem__, indexes))
            cpu_stats = list(map(cpu_stats.__getitem__, indexes))
            CPU_Util[instance.id] = [time_stamps, cpu_stats]
            # print("CPU Util Stats:", time_stamps, cpu_stats)
        return CPU_Util, ec2_instances


    def Cloudwatch_CpuUtil(self):
        '''
        gets cloudwatch cpu metrics for average and maximum
        '''
        metric_name = 'CPUUtilization'  # cloudwatch monitoring CPU
        stats = ['Average', 'Maximum']

        CPU_Util = {}

        ec2_instances = self.ec2resource.instances.filter(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
            
        for instance in ec2_instances:
            # CPU Util metrics
            time_stamps = []
            cpu_stats = {
                stats[0]:[], 
                stats[1]:[]
            }
            response = self.cloudwatch.get_metric_statistics(
                Period=1 * 60,
                StartTime=datetime.utcnow() - timedelta(seconds=30 * 60), # get datapoints for last 30 mins
                EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
                MetricName=metric_name,
                Namespace='AWS/EC2',
                Statistics=stats,
                Dimensions=[{'Name': 'InstanceId', 'Value': instance.id},]
            )

            for point in response['Datapoints']:
                hour = point['Timestamp'].hour
                minute = point['Timestamp'].minute
                time = hour + minute/60
                time_stamps.append(round(time, 2))
                for stat in stats:
                    cpu_stats[stat].append(round(point[stat], 2))
            indexes = list(range(len(time_stamps)))
            indexes.sort(key=time_stamps.__getitem__)
            time_stamps = list(map(time_stamps.__getitem__, indexes))
            for stat in stats:
                cpu_stats[stat] = list(map(cpu_stats[stat].__getitem__, indexes))
            CPU_Util[instance.id] = [time_stamps, cpu_stats] # 30 datapoints for last 30 mins, each datapoint = avg or max at curr min
            # print("CPU Util Stats:", time_stamps, cpu_stats)
        return CPU_Util, ec2_instances

    def Cloudwatch_TotalTwoMinuteAverage(self):
        '''
        gets last two maximum cpu percentages from cloudwatch cpu metrics for each instance
        used for the autoscaler to determine a policy change comparative to compare the cpu percent to
        '''
        cpu_util, ec2_instances = self.Cloudwatch_CpuUtil()
        num_active_workers = len(cpu_util.keys())
        cpu_cumulative_all_ec2 = 0
        if num_active_workers > 0:
            for ec2_id in cpu_util.keys():
                max_minute_2 = 0
                max_minute_1 = 0
                if len(cpu_util[ec2_id][1]['Maximum']) == 1:
                    max_minute_1 = cpu_util[ec2_id][1]['Maximum'][-1]
                elif len(cpu_util[ec2_id][1]['Maximum']) > 1:
                    max_minute_2 = cpu_util[ec2_id][1]['Maximum'][-2]
                    max_minute_1 = cpu_util[ec2_id][1]['Maximum'][-1]
                    # print("cpu util by minutes:")
                    # print(cpu_util[ec2_id][1]['Maximum'])
                last_max_avg = (max_minute_2 + max_minute_1) / 2
                cpu_cumulative_all_ec2 += last_max_avg
            cpu_average_all_ec2 = cpu_cumulative_all_ec2 / num_active_workers
            return cpu_average_all_ec2
        else:
            # no active workers
            return -1

    def Worker_Cloudwatch_HTTPReq(self):
        '''
        gets cloudwatch http requests for workers for graphing
        '''
        metric_name = 'HTTP_Requests'  # cloudwatch monitoring CPU
        stats = 'Average'

        HTTP_Req = {}

        ec2_instances = self.ec2resource.instances.filter(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])  

        for instance in ec2_instances:
            # HTTP req metric
            time_stamps = []        
            requests = []
            response = self.cloudwatch.get_metric_statistics(
                Period=1 * 60,
                StartTime=datetime.utcnow() - timedelta(seconds=30 * 60),
                EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
                MetricName=metric_name,
                Namespace=metric_name,
                Statistics=[stats],
                Dimensions=[{'Name': 'Instance_ID', 'Value': instance.id},]
            )

            # now loop through each datapoint to get a per minute statistic
            for point in response["Datapoints"]:
                hour = point['Timestamp'].hour
                minute = point['Timestamp'].minute
                time = hour + minute/60
                time_stamps.append(round(time, 2))
                # print("HTTP stats: ", point['Maximum'])
                requests.append(point['Average'])
            
            indexes = list(range(len(time_stamps)))
            indexes.sort(key=time_stamps.__getitem__)
            time_stamps = list(map(time_stamps.__getitem__, indexes))
            requests = list(map(requests.__getitem__, indexes))
            HTTP_Req['localhost'] = [time_stamps, requests]
            # for i in range(len(time_stamps)):
            #     print(time_stamps[i], requests[i])
        return HTTP_Req, ec2_instances


    def Worker_Cloudwatch_Count(self):
        '''
        gets cloudwatch cpu metrics for counts
        '''
        metric_name = 'NewConnectionCount'  # cloudwatch monitoring CPU
        stats = 'Sum'

        time_stamps = []        
        requests = []
        workers = {}

        response = self.cloudwatch.get_metric_statistics(
                Period=1 * 60,
                StartTime=datetime.utcnow() - timedelta(seconds=30 * 60), # get datapoints for last 30 mins
                EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
                MetricName=metric_name,
                Namespace='AWS/ApplicationELB',
                Statistics=[stats],
                Dimensions=[{'Name': 'LoadBalancer', 'Value': self.loadbalancer_arn_cloudwatch},]
            )
        for point in response["Datapoints"]:
            hour = point['Timestamp'].hour
            minute = point['Timestamp'].minute
            time = hour + minute/60
            time_stamps.append(round(time, 2))
            # print("Application ELB Point: ", point['Sum'])
            requests.append(point['Sum'])
        indexes = list(range(len(time_stamps)))
        indexes.sort(key=time_stamps.__getitem__)
        time_stamps = list(map(time_stamps.__getitem__, indexes))
        requests = list(map(requests.__getitem__, indexes))
        workers['elb'] = [time_stamps, requests]
        for i in range(len(time_stamps)):
            pass
            # print(time_stamps[i], requests[i])
        return workers

    def get_autoscaler_state(self):
        '''
        old dummy function is not used
        '''
        # Note: This code is placeholder, eventually will do this properly
        if self.autoscaler_state:
            self.autoscaler_state = False
            return False
        else:
            self.autoscaler_state = True
            return True


    
