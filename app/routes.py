from flask import render_template, url_for, flash, redirect, request
from app import app, db
from datetime import datetime, timedelta
from app.models import User
from app.forms import LoginForm
from werkzeug.urls import url_parse
from flask_login import current_user, login_user
import boto3
import os

# To ensure we always have an admin account we attempt to make it every time
# manager app only has one user, the admin
def setup():
    # function to attempt to create admin account every time the webapp is started
    # since at least one account needs administrator priveleges, it needs to exist
    try:
        admin = User(username='root', email='root@email.com')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        print("added admin,username: root, password: password")
    except:
        print("Admin user account already exists")
    return


#Default route must be logged in to see
setup()  # first, configure admin account
@app.route('/')
@app.route('/index')
def index():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('login'))
    flash("Welcome to Manger app - Use Navigation Bar to Manage/View Workers")
    return render_template('index.html')

# login page for administrator account
@app.route('/login', methods=['GET', 'POST'])
def login():
    # no need to login if you're already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    # form object of a login form class
    form = LoginForm()
    if form.validate_on_submit():  # method of this class to validate form
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            # check to see validity for username, if not valid try againn
            flash('Invalid username or password')
            return redirect(url_for('login'))
        # if valid, login the user
        login_user(user, remember=form.remember_me.data)
        return redirect(url_for('index'))
    return render_template('login.html', title='Sign In', form=form)


@app.route('/workers')
def workers():
    """
    Workers page displays:
    1. how many workers are active
    2. Chart 1: total CPU utilization of worker for past 30 mins (resolution 1 minute)
        x axis: time, y axis: CPU utilization
    3. Chart 2: Show HTTP requests recieved by each worker for past 30 mins
        x axis: time, y axis: HTTP requests per min
    4. Chart 3: workers in past 30 minutes
    """
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('index'))

    # creates a connection to aws services for ec2
    ec2 = boto3.resource('ec2')

    # find all instances with a filter name and running
    ec2_instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])


    # low level client to interact with cloud watch
    # tracks metrics for aws resources
    client = boto3.client('cloudwatch')
    metric_name = 'CPU_Utilization'  # cloudwatch monitoring CPU
    stats = 'Average'

    # dictionaries to generate chart 1 and 2
    CPU_Util = {}
    HTTP_Req = {}

    # loop through each instance to display metrics
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
        response = client.get_metric_statistics(
            Period=1 * 60,
            StartTime=datetime.utcnow() - timedelta(seconds=30 * 60),
            EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
            MetricName='HTTP_Requests',
            Namespace='HTTP_Requests',
            Statistics=['Maximum'],
            Dimensions=[
                    {
                    'Name': 'Instance_ID',
                    'Value': instance.id
                    },
                ]
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

        # CPU Util metrics
        time_stamps = []
        cpu_stats = []
        response = client.get_metric_statistics(
            Period=1 * 60,
            StartTime=datetime.utcnow() - timedelta(seconds=30 * 60),
            EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
            MetricName=metric_name,
            Namespace='AWS/EC2',
            Statistics=[stats],
            Dimensions=[{'Name': 'InstanceId', 'Value': instance.id}]
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
    
    # CPU_Util is a dictionary, with keys = instance_id, and values = [sorted time_stamps, cpu_utilization values]

    #for key, value in CPU_Util.items():
    #    print('Labels: ', value[0])
    #   print('CPU Utilization: ', value[1])

    if not CPU_Util:
        flash('Worker pool currently empty, please manually start some instances.', category='danger')
    else:
        flash('There are currently {} worker(s).'.format(len(CPU_Util)), category='success')
    return render_template('workers.html', instances = ec2_instances, 
                            CPU_Util = CPU_Util, HTTP_Req = HTTP_Req)


@app.route('/control_workers')
def control_workers():
    # user must be admin in order to manage workers
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('index'))

    title='Change Workers'
    return render_template('control.html', title=title)


@app.route('/increase_workers')
def increase_workers():
    # must be logged in to increase workers
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('index'))

    # create an ec2 client to make instances
    ec2 = boto3.resource('ec2', region_name='us-east-1')
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])

    # find all instances with a filter name and running
    ec2_instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])

    # before creating more workers, must check to see if max is reached
    check = 0
    for _ in ec2_instances:  # ec2_instances dont have __len__ callback, need loop
        check += 1
    if check >= 6:
        flash("Max workers have been reached (6 workers)")
        return redirect(url_for('index'))

    # create instance with ami, t2.micro instance
    # min/max DONT change (just creates 1 ec2 instance)
    # keyname specified to an earlier created one
    # security groupID is same as A1 group security rules
    # monitoring is true for cloudwatch metrics
    # try:
    ec2.create_instances(
        ImageId='ami-03fd75f2f5a87df48',
        MinCount=1,
        MaxCount=1,
        InstanceType='t2.micro',
        KeyName='ece1779-A1',
        SecurityGroupIds=['sg-05074cccdff882d74'],
        SubnetId='subnet-0f5a7a8fd40e35995',
        Monitoring={'Enabled': True}
        )
    flash("Worker creation successful! Please give the manager app a moment to count it")
    # except:
    flash("Unable to create instance")
    
    return redirect(url_for('control_workers'))

@app.route('/decrease_workers')
def decrease_workers():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('index'))

    return redirect(url_for('control_workers'))


@app.route('/stop',methods=['GET','POST'])
# Stop a EC2 instance
def stop():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators stop workers")
        return redirect(url_for('index'))

    ec2 = boto3.resource('ec2')
    ###### DO NOT CHANGE THE FILTER, REMOVING IT WILL DELETE ALL INSTANCES, INCLUDING THE ASSIGNMENT 1 INSTANCE! #######
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]).stop()
    ###### DO NOT CHANGE THE FILTER, REMOVING IT WILL DELETE ALL INSTANCES, INCLUDING THE ASSIGNMENT 1 INSTANCE! #######
    
    flash('Instances stopped/terminated successfully! Please manually restart instances from AWS to view charts.', category='success')
    return redirect(url_for('home'))


def create_key_pair(ec2):
    """
    Function to create a key for sshing into each created instance
    ec2 client is passed to this function to reduce redundancy
    !!Not currently used!!
    """
    ec2_client = boto3.client("ec2", region_name="us-west-2")
    # count instances to name key properly
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
    count = 0
    for _ in instances:
        count += 1
    keyname = f"ec2-key-pair-{count}"
    key_pair = ec2_client.create_key_pair(KeyName=keyname)

    private_key = key_pair["KeyMaterial"]

    # write private key to file with 400 permissions
    with os.fdopen(os.open(f"../keys/{keyname}.pem", os.O_WRONLY | os.O_CREAT, 0o400), "w+") as handle:
        handle.write(private_key)
    return keyname