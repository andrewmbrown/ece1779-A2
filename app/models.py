from app import db 
# hashing passwords
from werkzeug.security import check_password_hash, generate_password_hash
# authenticating users, checking active status, anonyimity, id
from flask_login import UserMixin
from app import login
from datetime import datetime


class ASPolicy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timeadded = db.Column(db.DateTime)
    cpu_increase_policy = db.Column(db.Float)
    cpu_decrease_policy = db.Column(db.Float)
    ratio = db.Column(db.Float)
    def __repr__(self):
        return '<ASPolicy {}>'.format(str(self.id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    def __repr__(self):
        return '<User {}>'.format(self.username)
    
    # Class now has method to do secure password verification
    # also to check password (hash again and check if they match)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login.user_loader
def load_user(id):
    return User.query.get(int(id))