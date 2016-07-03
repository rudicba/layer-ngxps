""" Reactive layer for install and manage Nginx Pagespeed
"""
from charmhelpers.core import hookenv
from charms.layer import ngxps

from charms.reactive import (
    when, when_any, when_not, set_state, remove_state, hook
)
from charms.reactive.helpers import data_changed


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

    ngxps_deb = hookenv.resource_get('ngxps_deb')

    if ngxps.install(ngxps_deb):
        set_state('ngxps.installed')
        set_state('ngxps.upgrade')

    set_state('ngxps.configure')


@when_any('config.changed', 'ngxps.configure')
def configure():
    """ Configure Nginx Pagespeed
    """
    if ngxps.configure():
        hookenv.status_set('maintenance', 'configuring nginx')
        set_state('ngxps.reload')

    set_state('ngxps.configured')
    remove_state('ngxps.configure')
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


@when('ngxps.ready', 'ngxps.upgrade')
def nginx_upgrade():
    """ Upgrade Nginx Pagespeed service
    """
    hookenv.status_set('active', 'upgrading nginx')
    if ngxps.upgrade():
        reset_state()
        update_status()


@when('ngxps.ready', 'ngxps.reload')
@when_not('ngxps.upgrade')
def nginx_reload():
    """ Reload Nginx Pagespeed service
    """
    hookenv.status_set('active', 'reloading nginx')
    if ngxps.reload():
        reset_state()
        update_status()


@when('ngxps.ready')
@when_not('web-engine.available')
def disable_sites():
    """ Disable any sites created by old relations
    """
    if not data_changed('web-engine.contexts', {}) or ngxps.no_sites():
        return

    ngxps.enable_sites('')

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
