""" Reactive layer for install and manage Nginx Pagespeed
"""
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
    remove_state('ngxps.restart')


@hook('upgrade-charm', 'install')
def install_ngxps():
    """ Install or upgrade Nginx Pagespeed, if new version is installed it
    will set two states: installed and upgrade.

    upgrade: set that service need to be restarted
    installed: set that Nginx is installed and ready for configure and start
    """
    hookenv.status_set('maintenance', 'installing nginx')

    ngxps_deb = hookenv.resource_get('ngxps_deb')

    if not ngxps_deb:
        hookenv.status_set('blocked', 'unable to fetch ngxps resource')
        return

    hookenv.status_set('maintenance', 'installing ngxps')

    if ngxps.install(ngxps_deb):
        set_state('ngxps.installed')
        set_state('ngxps.upgrade')

    # Nginx need to be configured.
    set_state('ngxps.configure')

    # After upgrade could be new templates for sites.
    data_changed('web-engine.contexts', {})


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


@when('ngxps.installed', 'ngxps.configured', 'dhe.ready',
      'tmpfs.ready', 'ngxps.cache_ready')
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
    if ngxps.enable_sites('default'):
        set_state('ngxps.reload')


@when('ngxps.ready', 'web-engine.available')
def add_sites(webengine):
    """ Add servers blocks for all relations with charm
    """
    if not data_changed('web-engine.contexts', webengine.contexts()):
        return

    sites = []

    for context in webengine.contexts():
        ngxps.add_site(context)
        sites.append(context['service_name'])

    if ngxps.enable_sites(*sites):
        set_state('ngxps.reload')


@when_not('memcache.available')
def remove_memcache():
    if not data_changed('memcache.contexts', {}):
        return

    if ngxps.set_cache():
        set_state('ngxps.reload')
        set_state('ngxps.cache_ready')


@when('memcache.available')
def add_memcache(memcache):
    memcaches = {'memcaches': memcache.memcache_hosts()}

    if not data_changed('memcache.contexts', memcaches):
        return

    if ngxps.set_cache(memcaches):
        set_state('ngxps.reload')
        set_state('ngxps.cache_ready')
