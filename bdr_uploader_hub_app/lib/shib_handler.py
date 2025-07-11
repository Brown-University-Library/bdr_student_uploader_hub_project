import logging
import pprint
from functools import wraps
from typing import Any, Callable, Tuple

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, HttpResponseServerError

log = logging.getLogger(__name__)


def shib_decorator(func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """
    Decorator for views that require Shibboleth authentication.

    Flow:
    - If user is already authenticated, the view is called as normal.
    - If user is not authenticated, attempts to provision a new user based on Shibboleth metadata.
    - If user creation fails, redirects to login page.
    - If user is successfully provisioned, logs user in and calls view.

    This function is triggered by views.shib_login(),
        which is called automatically by attempting to access an @login_required view.

    Note to self: the type-hint `Callable[..., HttpResponse]` above -- means that `func` is a function or method
        that can take any number of arguments, and returns an HttpResponse object
        which makes sense since this is a decorator.
    """
    log.debug('starting shib_decorator()')

    @wraps(func)  # all this line does is preserves function metadata
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        log.debug('starting shib_decorator wrapper()')
        ## if user's already authenticated, just call the view ------
        if request.user.is_authenticated:
            log.debug('user already authenticated.')
            return func(request, *args, **kwargs)
        ## process shib metadata ------------------------------------
        shib_metadata: dict = prep_shib_meta(request.META, request.get_host())
        ## provision user -------------------------------------------
        user: User | None = provision_user(shib_metadata)
        if not user:
            log.error('User creation failed; returning 500.')
            return HttpResponseServerError('Sorry, problem with authentication; ask developers to check the logs.')
        ## log user in and call view --------------------------------
        auth.login(request, user)
        log.info(f'user {user.username} logged in.')
        return func(request, *args, **kwargs)

    return wrapper

    ## end def shib_decorator()


def prep_shib_meta(request_metadata: dict, host: str) -> dict:
    """
    Extracts Shib metadata from WSGI environ.
    Returns extracted metadata as a dictionary.
    Called by wrapper().
    """
    log.debug('starting prep_shib_meta()')
    log.debug(f'request.META: ``{pprint.pformat(request_metadata)}``')

    shib_dct = {}
    if host in ['127.0.0.1', '127.0.0.1:8000', 'testserver']:  # allows for easy local testing
        shib_dct: dict = settings.TEST_SHIB_META_DCT
    else:
        for key, val in request_metadata.items():
            if key.startswith('Shib'):
                shib_dct[key] = val

    log.debug(f'returning new_dct, ``{pprint.pformat(shib_dct)}``')
    return shib_dct


def provision_user(shib_metadata: dict) -> User | None:
    """
    Creates or updates User object based on Shibboleth metadata.
    Returns User object or None
    Called by wrapper().
    """
    log.debug('starting provision_user()')
    ## ensure username and email and is-member-of -------------------
    username: str | None = shib_metadata.get('Shibboleth-eppn')
    if not username:
        log.warning('No eppn found in Shibboleth metadata')
    email: str | None = shib_metadata.get('Shibboleth-mail')
    if not email:
        log.warning('No email found in Shibboleth metadata')
    is_member_of: str | None = shib_metadata.get('Shibboleth-isMemberOf')
    if not is_member_of:
        log.warning('No isMemberOf found in Shibboleth metadata')
    if not username or not email or not is_member_of:
        return None
    ## store is-member-of groups ------------------------------------
    is_member_of_groups: list[str] = is_member_of.split(';')
    log.debug(f'is_member_of_groups, ``{is_member_of_groups}``')
    ## set user-object defaults -------------------------------------
    defaults: dict[str, str] = {
        'email': email,
        'first_name': shib_metadata.get('Shibboleth-givenName', ''),
        'last_name': shib_metadata.get('Shibboleth-sn', ''),
    }
    log.debug(f'username, ``{username}``')
    log.debug(f'defaults, ``{pprint.pformat(defaults)}``')
    ## create or update user ----------------------------------------
    try:
        result: Tuple[User, bool] = User.objects.update_or_create(username=username, defaults=defaults)
        (user, created) = result
        log.debug(f'user-created, ``{created}``')
        user.save()
        try:
            ## update userprofile -----------------------------------------
            user.userprofile.is_member_of_groups = is_member_of_groups
            user.userprofile.save()
        except Exception:
            log.exception('Error updating user profile')
            log.debug(f'User profile details: {pprint.pformat(user.userprofile.__dict__)}')
    except Exception:
        log.exception('Error creating user')
        user = None
    log.debug(f'returning user, ``{user}``')
    return user

    ## end def provision_user()


# def provision_user(shib_metadata: dict) -> User | None:
#     """
#     Creates or updates User object based on Shibboleth metadata.
#     Returns User object or None
#     Called by wrapper().
#     """
#     log.debug('starting provision_user()')
#     ## ensure username and email ------------------------------------
#     username: str | None = shib_metadata.get('Shibboleth-eppn')
#     if not username:
#         log.warning('No eppn found in Shibboleth metadata')
#     email: str | None = shib_metadata.get('Shibboleth-mail')
#     if not email:
#         log.warning('No email found in Shibboleth metadata')
#     if not username or not email:
#         return None
#     ## set defaults -------------------------------------------------
#     defaults: dict[str, str] = {
#         'email': email,
#         'first_name': shib_metadata.get('Shibboleth-givenName', ''),
#         'last_name': shib_metadata.get('Shibboleth-sn', ''),
#     }
#     log.debug(f'username, ``{username}``')
#     log.debug(f'defaults, ``{pprint.pformat(defaults)}``')
#     ## create or update user ----------------------------------------
#     try:
#         result: Tuple[User, bool] = User.objects.update_or_create(username=username, defaults=defaults)
#         (user, created) = result
#         log.debug(f'user-created, ``{created}``')
#         user.save()
#     except Exception:
#         log.exception('Error creating user')
#         user = None
#     log.debug(f'returning user, ``{user}``')
#     return user

#     ## end def provision_user()
