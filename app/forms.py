from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired
from app.models import User


# Login form specifies data input when logging into the site
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

class AutoscaleForm(FlaskForm):
    cpu_increase_policy = DecimalField('Increase Policy', validators=[DataRequired()])
    cpu_decrease_policy = DecimalField('Decrease Policy', validators=[DataRequired()])
    ratio_grow = DecimalField('Ratio Grow', validators=[DataRequired()])
    ratio_shrink = DecimalField('Ratio Shrink', validators=[DataRequired()])
    submit = SubmitField('Enter Policy')
