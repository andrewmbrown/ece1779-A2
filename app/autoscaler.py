import time 
from datetime import datetime, timedelta 
import schedule 

import webservices as wbs 
import app 
import db 
from models import ASPolicy 


def autoscaler(average_cpu_util, policy):
    if not policy or average_cpu_util == -1:
        return -1
    elif average_cpu_util > policy['cpu-thresh-grow']:
        r = wbs.increase_workers(ratio=True, policy['ratio'])
    elif average_cpu_util < policy['cpu-thresh-shrink']:
        r = wbs.decrease_workers(ratio=True, policy['ratio'])
    else:
        return -1
    return 200

def check_autoscaler_policy(s=120): # 120 = 2 min
    t_1 = datetime.now()
    t_0 = t_1 - timedelta(seconds=s)
    active_targets = wbs.ELB_worker_target_status(False, True, False)
    cpu_cumulative = 0
    average_cpu_util = 0
    total_active_workers = len(active_targets)
    if total_active_workers == 0:
        average_cpu_util = -1
    else:
        for target in active_targets:
            target_id = target['id']
            r = wbs.Cloudwatch_CPU_usage_metrics(target_id, t_0, t_1)
            cpu_cumulative += r['cpu_span']
    average_cpu_util = cpu_cumulative / total_active_workers
    db.session.commit()
    curr_policy = ASPolicy.query.order_by(ASPolicy.timeadded.desc()).first()
    latest_policy = {}
    if curr_policy:
        latest_policy = {
            'cpu-thresh-grow': curr_policy.cpu_grow_policy,
            'cpu-thresh-shrink': curr_policy.cpu_shrink_policy,
            'ratio': curr_policy.cpu_ratio
        }
    auto_resp = autoscaler(average_cpu_util, latest_policy)
    return auto_resp # 200 OK or -1 BAD 

def run_continuous():
    schedule.every().minute.do(check_autoscaler_policy)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    run_continuous()

