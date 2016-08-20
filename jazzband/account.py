from flask import Blueprint, redirect, url_for, flash, request
from flask_login import (LoginManager, current_user,
                         login_user, logout_user, login_required)

from .decorators import templated
from .forms import LeaveForm
from .github import github
from .models import db, User, update_user_email_addresses

login_manager = LoginManager()
login_manager.login_view = 'account.login'
account = Blueprint('account', __name__, url_prefix='/account')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


@account.app_template_global()
def default_url():
    return url_for('content.index')


@github.access_token_getter
def token_getter():
    if current_user.is_authenticated:
        return current_user.access_token


@account.route('')
@login_required
@templated()
def dashboard():
    return {}


@account.route('/login')
def login():
    if current_user.is_authenticated:
        next_url = url_for('account.dashboard')
        return redirect(next_url)

    # default fallback is to initiate the GitHub auth workflow
    return github.authorize(scope=github.scope)


@account.route('/callback')
@github.authorized_handler
def callback(access_token):
    # first get the profile data for the user with the given access token
    user_data = github.get_user(access_token=access_token)

    # and see if the user is already in our database
    user = User.query.filter_by(id=user_data['id']).first()

    # if not, sync the data from GitHub with our database
    if user is None:
        user_data['access_token'] = access_token
        results = User.sync([user_data])
        user, created = results[0]
    else:
        # if it can be found, update the access token
        user.access_token = access_token
        db.session.commit()

    # fetch the current set of email addresses from GitHub
    update_user_email_addresses(user)

    # remember the user_id for the next request
    login_user(user)

    # then redirect to the account dashboard
    return redirect(url_for('account.dashboard'))


@account.route('/join')
@login_required
@templated()
def join():
    next_url = default_url()

    if current_user.is_banned:
        flash("You've been banned from Jazzband")
        logout_user(current_user)
        return redirect(next_url)
    elif current_user.is_member:
        flash("You're already a member of Jazzband")
        return redirect(next_url)

    update_user_email_addresses(current_user)
    has_verified_emails = current_user.check_verified_emails()

    membership = None
    if has_verified_emails:
        membership = github.join_organization(current_user.login)
        if membership:
            flash("Jazzband has asked GitHub to send you an invitation")

    return {
        'next_url': 'https://github.com/jazzband/roadies/wiki/Welcome',
        'membership': membership,
        'org_id': github.org_id,
        'has_verified_emails': has_verified_emails,
    }


@account.route('/leave', methods=['GET', 'POST'])
@login_required
@templated()
def leave():
    next_url = default_url()
    if not current_user.is_member:
        return redirect(next_url)

    form = LeaveForm(request.form)
    if request.method == 'POST' and form.validate():
        response = github.leave_organization(current_user.login)
        if response is None:
            flash('Leaving the organization failed. '
                  'Please try again or open a ticket for the roadies.')
        else:
            current_user.is_member = False
            db.session.commit()
            logout_user()
            flash('You have been removed from the Jazzband GitHub '
                  'organization. See you soon!')
        return redirect(next_url)
    return {'form': form}


@account.route('/logout')
def logout():
    logout_user()
    return redirect(default_url())
