""" Reactive layer for install and manage Nginx Pagespeed
"""
import os

from charmhelpers.core import hookenv
from charms.layer import ngxps

from charms.reactive import (
    when, when_any, when_not, set_state, remove_state, hook
)
from charms.reactive.helpers import data_changed, is_state


def reset_state():
    """ Reset any state that tell reactive to restart nginx, usefull to ensure
    that service will not be restarted twice.
    """
    remove_state('ngxps.reload')
    remove_state('ngxps.upgrade')


@hook('upgrade-charm', 'install')
def install():
    """ Install or upgrade Nginx Pagespeed, if new version is installed it
    will set two states: installed and upgrade.

    upgrade: set that service need to be restarted
    installed: set that Nginx is installed and ready for configure and start
    """
    hookenv.status_set('maintenance', 'installing nginx')

    # Try to get .deb file from charm path
    ngxps_deb = os.path.join(
        hookenv.charm_dir(), 'resources', 'nginx_1.10.1-1_amd64.deb')

    # If .deb is not provided for charm, get it from resources
    if not os.path.isfile(ngxps_deb):
        ngxps_deb = hookenv.resource_get('ngxps_deb')

    # If couldn't find any .deb, set status to maintenance
    if not os.path.isfile(ngxps_deb):
        hookenv.status_set('maintenance',
                           'waiting for nginx pagespeed deb resource')
    # Otherwise install provided deb package
    else:
        if ngxps.install(ngxps_deb):
            set_state('ngxps.installed')
            set_state('ngxps.upgrade')
        # Nginx need to be configured
        set_state('ngxps.configure')


@when_any('config.changed', 'ngxps.configure')
def configure():
    """ Configure Nginx Pagespeed
    """
    # Function configure() return True if any config file change
    if ngxps.configure():
        hookenv.status_set('maintenance', 'configuring nginx')
        set_state('ngxps.reload')

    set_state('ngxps.configured')
    remove_state('ngxps.configure')
    # Ensure ngxps is enabled at boot time
    ngxps.enable()


@when('config.changed.tmpfs_size')
def create_tmpfs():
    """ Create cache filesystem
    """
    config = hookenv.config()

    hookenv.status_set('maintenance', 'creating cache')
    with ngxps.stop_start():
        ngxps.create_tmpfs(config['tmpfs_size'])

    set_state('tmpfs.ready')


@when('config.changed.dhe_size')
def create_dhe():
    """ Create Diffie-Hellman key
    """
    config = hookenv.config()

    hookenv.status_set('maintenance', 'creating dhe')
    with ngxps.stop_start():
        ngxps.create_dhe(config['dhe_size'])

    set_state('dhe.ready')


@when('ngxps.ready')
def update_status():
    """ Set Nginx Pagespeed status
    """
    _, message = hookenv.status_get()

    if not ngxps.validate_config():
        hookenv.status_set('maintenance', 'nginx configuration test failed')
        return

    if ngxps.running():
        if message != 'nginx running':
            hookenv.status_set('active', 'nginx running')
    else:
        if message != 'nginx not running':
            hookenv.status_set('maintenance', 'nginx not running')


@when('ngxps.installed', 'ngxps.configured', 'dhe.ready', 'tmpfs.ready')
@when_not('ngxps.ready')
def start():
    """ Start Nginx Pagespeed service
    """
    hookenv.status_set('active', 'starting nginx')
    if ngxps.start():
        set_state('ngxps.ready')
        reset_state()
        update_status()


@when('ngxps.ready')
@when_any('ngxps.upgrade', 'ngxps.reload', 'ngxps.restart')
def nginx_upgrade():
    """ Upgrade, reload or restart nginx

    if multiple state is reached give priority to restart then upgrade and last
    priority to reload.
    """
    if is_state('ngxps.restart'):
        hookenv.status_set('active', 'restarting nginx')
        if ngxps.restart():
            hookenv.status_set('active', 'nginx successfully restarted')
    elif is_state('ngxps.upgrade'):
        hookenv.status_set('active', 'upgrading nginx')
        if ngxps.upgrade():
            hookenv.status_set('active', 'nginx successfully upgraded')
    elif is_state('ngxps.reload'):
        hookenv.status_set('active', 'reloading nginx')
        if ngxps.reload():
            hookenv.status_set('active', 'nginx successfully reloaded')

    reset_state()
    update_status()


@when('ngxps.ready')
@when_not('web-engine.available')
def disable_sites():
    """ Disable any sites created by old relations
    """
    if not data_changed('web-engine.contexts', {}):
        return

    context = {
        'service_name': 'default',
        'root': '/usr/local/nginx/html',
    }

    ngxps.add_site(context)
    ngxps.enable_sites('default')

    set_state('ngxps.reload')


@when('ngxps.ready', 'web-engine.available')
def add_sites(webengine):
    """ Add servers blocks for all relations with charm
    """
    # TODO: on upgrade sometimes templates changes, so this function needed
    # to be runned not only if context change.
    if not data_changed('web-engine.contexts', webengine.contexts()):
        return

    sites = []

    for context in webengine.contexts():
        ngxps.add_site(context)

        sites.append(context['service_name'])

    ngxps.enable_sites(*sites)
    set_state('ngxps.reload')
