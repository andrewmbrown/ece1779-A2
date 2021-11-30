import time 
from datetime import datetime, timedelta 
import schedule # must install via pip
 
import aws
import sqlite3 

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

    con = sqlite3.connect("../app.db")
    cur = con.cursor()
    z = cur.execute("SELECT * FROM as_policy ORDER BY timeadded;")
    r = cur.fetchall()
    con.close()

    curr_policy = {}
    if len(r) > 0:
        last_aspolicy = r[-1]
        curr_policy['cpu_grow_policy'] = last_aspolicy[2]
        curr_policy['cpu_shrink_policy'] = last_aspolicy[3]
        curr_policy['cpu_ratio_grow'] = last_aspolicy[4]
        curr_policy['cpu_ratio_shrink'] = last_aspolicy[5] 

    '''
    if curr_policy:
        latest_policy = {
            'cpu-thresh-grow': curr_policy['cpu_grow_policy'],
            'cpu-thresh-shrink': curr_policy['cpu_shrink_policy'],
            'ratio-grow': curr_policy['cpu_ratio_grow'],
            'ratio-shrink': curr_policy['cpu_ratio_shrink']
        }
    latest_policy = {
        'cpu-thresh-grow': 50,
        'cpu-thresh-shrink': 2.0,
        'ratio-grow': 2.0,
        'ratio-shrink': 0.25
    }
    '''
    auto_resp = autoscaler(average_cpu_util, curr_policy)
    return auto_resp # 200 OK or -1 BAD 

def run_continuous():
    schedule.every().minute.do(check_autoscaler_policy)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_continuous()

