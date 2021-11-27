import boto3
import json
import time
from datetime import datetime, timedelta
from app import access
# initialize the boto3 stuff here universally

class AwsClient:
    def __init__(self) -> None:
        # User Dependent Values
        self.AWS_ACC_KEY = access.access_keys['AWS_ACC_KEY']
        self.AWS_SEC_KEY = access.access_keys['AWS_SECRET_KEY']
        self.keypair_name ='ece1779-A1'
        self.security_group=['sg-05074cccdff882d74']
        self.target_group_arn = 'arn:aws:elasticloadbalancing:us-east-1:962907337984:targetgroup/ece1779-A2/9661f1382c6d2178'

        # Universally Constant Values
        self.ec2 = boto3.client('ec2',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY, 
                region_name="us-east-1")
        self.ec2client = boto3.resource('ec2', region_name='us-east-1')
        self.elb = boto3.client('elbv2',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY, 
                region_name="us-east-1")
        self.cloudwatch = boto3.client('cloudwatch',
                aws_access_key_id=self.AWS_ACC_KEY, 
                aws_secret_access_key=self.AWS_SEC_KEY, 
                region_name="us-east-1")
        self.AMI_IMAGE_ID = "ami-03fd75f2f5a87df48"
        self.instance_type ='t2.micro'
        self.monitoring = {
            'Enabled': True
        }
        self.autoscaler_state = False


    def WAIT_startup_complete(self, worker_id):
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
        r = self.ec2.describe_instances()
        rr = r['Reservations']
        rel_wk = [rr[i] for i in range(len(rr)) if rr[i]['Instances'][0]['ImageId'] == self.AMI_IMAGE_ID]
        # rel_wk[0].keys() = [Groups, Instances, OwnerId, ReservationId]
        # if terminated, smaller size instance package than if running
        wk_i_data = [rel_wk[i]['Instances'][0] for i in range(len(rel_wk))]
        worker_data_filtered = [{'id': wk_i_data[u]['InstanceId'], 'state': wk_i_data[u]['State']['Name']} for u in range(len(wk_i_data))]
        return worker_data_filtered

    def ELB_worker_target_status(self, get_all_targeted=True, get_active_targets=False, get_untargeted=False): # DONE
        # pick one of get_ingroup, get_idlers, or get_all = true, inside the code 
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
        untargeted_workers = self.ELB_worker_target_status(get_all_targeted=False, get_active_targets=False, get_untargeted=True)
        stopped_workers = [worker for worker in untargeted_workers if worker['state'] == 'stopped']
        return stopped_workers

    def EC2_create_worker(self): # DONE
        '''
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
        '''
        # replace below with:
        # SecurityGroupIds=['sg-05074cccdff882d74'], 
        # SubnetId='subnet-0f5a7a8fd40e35995',
        # KeyName='ece1779-A1',
        try:
            r = self.ec2.run_instances(
                ImageId=self.AMI_IMAGE_ID,
                MinCount=1,
                MaxCount=1,
                InstanceType=self.instance_type,
                KeyName=self.keypair_name,
                SecurityGroupIds=self.security_group, 
                Monitoring=self.monitoring,
                SubnetId='subnet-039865d4c3b7aa9a5'
            )
            worker = {
                'id': r['Instances'][0]['InstanceId'],
                'launchtime': r['Instances'][0]['LaunchTime'],
                'monitoring': r['Instances'][0]['Monitoring'],
                'state': r['Instances'][0]['State']
            }
            print("Created worker: {}".format(worker['id']))
            return {'response': r, 'worker': worker, 'FAILED': 0}
        except:
            print("Unable to create worker!")
            return {'response': None, 'worker': None, 'FAILED': -1}

    def EC2_increase_workers(self, ratio=False, amount=2.0): # ratio=False, amount ignored as just 1; ratio=True, amount used
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
                    print("ERROR: Could not increase workers!")
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
            return -1

    def EC2_decrease_workers(self, ratio=False, amount=0.5): # ratio=False, amount ignored as just 1; ratio=True, amount used
        DEREG_HTTP_code = -1
        STOP_HTTP_code = -1
        if not ratio:
            active_workers = self.ELB_worker_target_status(get_all_targeted=False, get_active_targets=True, get_untargeted=False)
            if len(active_workers) == 0:
                print("No workers active")
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
            return -1 

    def Cloudwatch_CPU_usage_metrics(self, worker_id, start_s, end_s):
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
        print("response:")
        print(r)
        if 'Datapoints' in r:
            datapoints = []
            for dp in r['Datapoints']:
                datapoints.append([
                    int(dp['Timestamp'].timestamp() * 1000),
                    float(dp['Maximum'])
                ])
            print("full datapoints:")
            print(datapoints)
            return json.dumps(sorted(datapoints, key=lambda x: x[0]))
        return json.dumps([[]])

    # testbench here with a name main 

    def Cloudwatch_CpuUtil(self):
        metric_name = 'CPUUtilization'  # cloudwatch monitoring CPU
        stats = 'Average'

        CPU_Util = {}

        ec2_instances = self.ec2client.instances.filter(
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
            print("CPU Util Stats:", time_stamps, cpu_stats)
        return CPU_Util, ec2_instances

    def Cloudwatch_HTTPReq(self):
        metric_name = 'HTTP_Requests'  # cloudwatch monitoring CPU
        stats = 'Maximum'
        HTTP_Req = {}

        ec2_instances = self.ec2client.instances.filter(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])  

        for instance in ec2_instances:

            # HTTP req metric
            time_stamps = []        
            requests = []
            # using cloudwatch, get metrics from ec2 instance within a window of time
            """
            response, dictionary containing metrics
            Period: 60s
            StartTime: Start monitoring 30 mins in past from utc
            Endtime: Stop monitoring at utc (window=30mins)
            MetricName: name of this measurement
            Namespace: HTTP request name
            Statistics: Maximum value from single observation
            Dimensions: specific instance specified
            """
            response = self.cloudwatch.get_metric_statistics(
                Period=1 * 60,
                StartTime=datetime.utcnow() - timedelta(seconds=30 * 60),
                EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
                MetricName=metric_name,
                Namespace=metric_name,
                Statistics=[stats],
                Dimensions=[{'Name': 'Instance_ID','Value': instance.id},]
            )

            requests = []
            time_stamps = []
            # now loop through each datapoint to get a per minute statistic
            for point in response["Datapoints"]:
                hour = point['Timestamp'].hour
                minute = point['Timestamp'].minute
                time = hour + minute/60
                time_stamps.append(round(time, 2))
                print("HTTP stats: ", point['Maximum'])
                requests.append(point['Maximum'])
            
            indexes = list(range(len(time_stamps)))
            indexes.sort(key=time_stamps.__getitem__)
            time_stamps = list(map(time_stamps.__getitem__, indexes))
            requests = list(map(requests.__getitem__, indexes))
            HTTP_Req['localhost'] = [time_stamps, requests]
            for i in range(len(time_stamps)):
                print(time_stamps[i], requests[i])
        return HTTP_Req, ec2_instances
    '''
    if __name__ == "__main__":
        r = EC2_create_worker()
        new_worker = r['worker']
        state_r_1 = ec2.describe_instance_status(InstanceIds=[new_worker['id']])
        state_r_2
    '''


    def get_autoscaler_state(self):
        # Note: This code is placeholder, eventually will do this properly
        if self.autoscaler_state:
            self.autoscaler_state = False
            return False
        else:
            self.autoscaler_state = True
            return True


    
