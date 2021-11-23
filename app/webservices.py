import boto3
import json
import time 
from access import access_keys
# initialize the boto3 stuff here universally

AWS_ACC_KEY = access_keys['AWS_ACC_KEY']
AWS_SEC_KEY = access_keys['AWS_SECRET_KEY']
AMI_IMAGE_ID = "ami-03fd75f2f5a87df48"

'''
bt3 = boto3.Session(
    aws_access_key_id=AWS_ACC_KEY,
    aws_secret_access_key=AWS_SEC_KEY,
    region_name='us-east-1'
)
'''

ec2 = boto3.client('ec2',
    aws_access_key_id=AWS_ACC_KEY, 
    aws_secret_access_key=AWS_SEC_KEY, 
    region_name="us-east-1")
elb = boto3.client('elbv2',
    aws_access_key_id=AWS_ACC_KEY, 
    aws_secret_access_key=AWS_SEC_KEY, 
    region_name="us-east-1")
cloudwatch = boto3.client('cloudwatch',
    aws_access_key_id=AWS_ACC_KEY, 
    aws_secret_access_key=AWS_SEC_KEY, 
    region_name="us-east-1")


'''
ec2 = bt3.resource('ec2')
elb = bt3.resource('elbv2')
cloudwatch = bt3.resource('cloudwatch')
'''
target_group_arn = "arn:aws:elasticloadbalancing:us-east-1:322026937675:targetgroup/testgroup/831071efa81bba8d"
# elb.register_targets(TargetGroupArn=target_group_arn, Targets=[{'Id': wid[0]['InstanceId'], 'Port':80}])

def WAIT_startup_complete(worker_id):
    r = ec2.describe_instance_status(InstanceIds=[worker_id])
    while len(r['InstanceStatuses']) == 0:
        time.sleep(5)
        r = ec2.describe_instance_status(InstanceIds=[worker_id])
    while r['InstanceStatuses'][0]['InstanceState']['Name'] != 'running':
        time.sleep(5)
        r = ec2.describe_instance_status(InstanceIds=[worker_id])
    time.sleep(5)
    return True 

def ELB_filter_instances_by_ami(): # DONE
    r = ec2.describe_instances()
    rr = r['Reservations']
    rel_wk = [rr[i] for i in range(len(rr)) if rr[i]['Instances'][0]['ImageId'] == AMI_IMAGE_ID]
    # rel_wk[0].keys() = [Groups, Instances, OwnerId, ReservationId]
    # if terminated, smaller size instance package than if running
    wk_i_data = [rel_wk[i]['Instances'][0] for i in range(len(rel_wk))]
    worker_data_filtered = [{'id': wk_i_data[u]['InstanceId'], 'state': wk_i_data[u]['State']['Name']} for u in range(len(wk_i_data))]
    return worker_data_filtered

def ELB_worker_target_status(get_all_targeted=True, get_active_targets=False, get_untargeted=False): # DONE
    # pick one of get_ingroup, get_idlers, or get_all = true, inside the code 
    elb_r = elb.describe_target_health(TargetGroupArn=target_group_arn)
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
        all_workers_by_ami = ELB_filter_instances_by_ami()
        non_targeted_workers = [worker for worker in all_workers_by_ami if worker['id'] not in target_worker_ids]
        return non_targeted_workers
    else:
        return []

def EC2_get_stopped_workers():
    untargeted_workers = ELB_worker_target_status(get_all_targeted=False, get_active_targets=False, get_untargeted=True)
    stopped_workers = [worker for worker in untargeted_workers if worker['state'] == 'stopped']
    return stopped_workers

def EC2_create_worker(): # DONE
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
        r = ec2.run_instances(
            ImageId=AMI_IMAGE_ID,
            MinCount=1,
            MaxCount=1,
            InstanceType='t2.micro',
            KeyName='ece1779-a2-ec2-key',
            SecurityGroupIds=['sg-0e1f1e5bb640b7d1a'], 
            Monitoring={'Enabled': True}
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

def EC2_increase_workers(ratio=False, amount=2.0): # ratio=False, amount ignored as just 1; ratio=True, amount used
    if not ratio:
        # increase by 1

        w_id = None
        stopped_workers = EC2_get_stopped_workers()
        if len(stopped_workers) > 0:
            w_id = stopped_workers[0]['id']
            ec2.start_instances(InstanceIds=[w_id])
        else:
            r = EC2_create_worker()
            if r['FAILED'] == -1:
                print("ERROR: Could not increase workers!")
                return -1
            w_id = r['worker']['id']

        WAIT_startup_complete(w_id) # wait on the startup to complete

        r_elb = elb.register_targets(TargetGroupArn=target_group_arn, Targets=[{'Id': w_id, 'Port':80}])
        if r_elb:
            if 'ResponseMetadata' in r_elb:
                if 'HTTPStatusCode' in r_elb['ResponseMetadata']:
                    HTTP_code = r_elb['ResponseMetadata']['HTTPStatusCode']
                    return HTTP_code
        return -1 
    else:
        return -1

def EC2_decrease_workers(ratio=False, amount=0.5): # ratio=False, amount ignored as just 1; ratio=True, amount used
    DEREG_HTTP_code = -1
    STOP_HTTP_code = -1
    if not ratio:
        active_workers = ELB_worker_target_status(get_all_targeted=False, get_active_targets=True, get_untargeted=False)
        if len(active_workers) == 0:
            print("No workers active")
            return -1
        else:
            w_id = active_workers[0]['id'] # deregister and stop this worker 
            # deregister worker
            r_elb = elb.deregister_targets(TargetGroupArn=target_group_arn, Targets=[{'Id': w_id}])
            if r_elb:
                if 'ResponseMetadata' in r_elb:
                    if 'HTTPStatusCode' in r_elb['ResponseMetadata']:
                        DEREG_HTTP_code = r_elb['ResponseMetadata']['HTTPStatusCode']
            if int(DEREG_HTTP_code) != 200:
                return -1
            else: 
                r_ec2 = ec2.stop_instances(InstanceIds=[w_id])
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

def Cloudwatch_CPU_usage_metrics(worker_id, start_s, end_s):
    return 

# testbench here with a name main 

'''
if __name__ == "__main__":
    r = EC2_create_worker()
    new_worker = r['worker']
    state_r_1 = ec2.describe_instance_status(InstanceIds=[new_worker['id']])
    state_r_2
'''


    


    
