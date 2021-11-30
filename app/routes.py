from flask import render_template, url_for, flash, redirect
from app import app, db, aws
from app.models import User, ASPolicy
from app.forms import LoginForm, AutoscaleForm
from flask_login import current_user, login_user, logout_user


# To ensure we always have an admin account we attempt to make it every time
# manager app only has one user, the admin
def setup():
    # function to attempt to create admin account every time the webapp is started
    # since at least one account needs administrator priveleges, it needs to exist
    awscli = aws.AwsClient() # configure aws client
    try:
        admin = User(username='root', email='root@email.com')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        print("added admin,username: root, password: password")
    except:
        print("Admin user account already exists")
        db.session.rollback()
    return awscli


#Default route must be logged in to see
awscli = setup()  # first, configure admin account and aws services class
@app.route('/')
@app.route('/index')
def index():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('login'))
    flash("Welcome to Manger app - Use Navigation Bar to Manage/View Workers")
    workers = awscli.Worker_Cloudwatch_Count()
    workers = workers['elb']
    return render_template('index.html', workers=workers)

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

@app.route('/logout')
def logout():
    if current_user.is_authenticated: pass  # only see anything if logged in
    else:
        flash("Please login")
        return redirect(url_for('login'))
    logout_user()
    flash("Successfully logged out")
    return redirect(url_for('index'))

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

    # call both functions for CPUUTIL + HTTP Req data to generate graphs
    CPU_Util, ec2_instances = awscli.Worker_Cloudwatch_CpuUtil()
    HTTP_Req, ec2_instances = awscli.Worker_Cloudwatch_HTTPReq()
    
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

    # call webservices fxn to either run or create a worker
    code = awscli.EC2_increase_workers()
    
    if code == 200: flash("Worker Increase Successful!")  # http success
    else: flash("Unable to Create Instance")  # http success

    return redirect(url_for('control_workers'))


@app.route('/decrease_workers')
def decrease_workers():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('index'))

    # call webservices to decrease workers
    code = awscli.EC2_decrease_workers()

    if code == 200: flash("Worker Decrease Successful!")  # http success
    else: flash("Unable to Stop Worker")

    return redirect(url_for('control_workers'))


@app.route('/autoscaler', methods=['GET', 'POST'])
def autoscaler():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can manage workers")
        return redirect(url_for('index'))
    form = AutoscaleForm()
    if form.validate_on_submit():  # method of this class to validate form
        aspol = ASPolicy(cpu_increase_policy=99.0, cpu_decrease_policy=0.0, ratio_grow=2.0, ratio_shrink=0.5)
        db.session.add(aspol)
        try:
            db.session.commit()
        except:
            flash('Autoscaling policy set failed')
            db.session.rollback()
            return redirect(url_for('index'))
        flash('New autoscaling policy set!')
    # status = awscli.get_autoscaler_state()
    return render_template('autoscaler.html', form=form)


# Stop all ec2 instances, then shut down
@app.route('/stop')
def stop():
    if current_user.is_authenticated:  # only see anything if logged in
        flash("Currently logged in")
    else:
        flash("Please login, only administrators can stop workers")
        return redirect(url_for('index'))

    # aws cli to terminate all workers
    code = awscli.EC2_terminate_all_workers()
    
    if code == 200: flash("All Workers Terminated!")  # http success
    else: flash("Unable to Terminate Workers")

    return redirect(url_for('index'))


# delete all data on s3 and rds
@app.route('/delete')
def delete():
    if current_user.is_authenticated:  # only see anything if logged in
        pass
    else:
        flash("Please login, only administrators can stop workers")
        return redirect(url_for('index'))

    # aws cli to delete all worker data
    code = awscli.S3_rds_delete_all_data()   
    
    if code == 200: flash("All Data Deleted")  # http success
    else: flash("Unable to Delete Data")

    return redirect(url_for('index'))
