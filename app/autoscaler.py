import time 
from datetime import datetime, timedelta 
import schedule # must install via pip

import webservices as wbs 
import aws
# import db
# from models import ASPolicy 

A = aws.AwsClient()

def autoscaler(average_cpu_util, policy):
    if not policy or average_cpu_util == -1:
        return -1
    elif average_cpu_util > policy['cpu-thresh-grow']:
        r = A.EC2_increase_workers(True, policy['ratio-grow'])
        print(average_cpu_util, policy['cpu-thresh-grow'])
        print("Increase")
        print(r)
    elif average_cpu_util < policy['cpu-thresh-shrink']:
        r = A.EC2_decrease_workers(True, policy['ratio-shrink'])
        print(average_cpu_util, policy['cpu-thresh-shrink'])
        print("Decrease")
        print(r)
    else:
        print(average_cpu_util, policy['cpu-thresh-grow'], policy['cpu-thresh-shrink'])
        print("Stable")
        return 200
    return 200

def check_autoscaler_policy(): # 120 = 2 min
    average_cpu_util = A.Cloudwatch_TotalTwoMinuteAverage()

    db.session.commit()
    curr_policy = ASPolicy.query.order_by(ASPolicy.timeadded.desc()).first()
    latest_policy = {}
    if curr_policy:
        latest_policy = {
            'cpu-thresh-grow': curr_policy.cpu_grow_policy,
            'cpu-thresh-shrink': curr_policy.cpu_shrink_policy,
            'ratio-grow': curr_policy.cpu_ratio_grow,
            'ratio-shrink': curr_policy.cpu_ratio_shrink
        }
    '''
    latest_policy = {
        'cpu-thresh-grow': 50,
        'cpu-thresh-shrink': 2.0,
        'ratio-grow': 2.0,
        'ratio-shrink': 0.25
    }
    '''
    auto_resp = autoscaler(average_cpu_util, latest_policy)
    return auto_resp # 200 OK or -1 BAD 

def run_continuous():
    schedule.every().minute.do(check_autoscaler_policy)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_continuous()

