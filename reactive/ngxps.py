from charmhelpers.core import hookenv

from charms.layer import ngxps

from charms.reactive import (when, when_not, set_state, remove_state, hook)
from charms.reactive.helpers import data_changed


config = hookenv.config()


def reset_state():
    remove_state('ngxps.restart')
    remove_state('ngxps.reload')
    remove_state('ngxps.upgrade')


@hook('upgrade-charm', 'install')
def install():
    hookenv.status_set('maintenance', 'installing nginx')

    nginx = hookenv.resource_get('nginx')
    nps = hookenv.resource_get('nps')
    psol = hookenv.resource_get('psol')
    naxsi = hookenv.resource_get('naxsi')

    if nginx and nps and psol and naxsi:
        if ngxps.install(nginx, nps, psol, naxsi):
            set_state('ngxps.installed')
            set_state('ngxps.upgrade')
    else:
        hookenv.status_set('blocked', 'could not fetch all needed resources')


@when('config.changed')
def configure():
    hookenv.status_set('maintenance', 'configuring nginx')
    ngxps.configure()
    ngxps.enable()

    set_state('ngxps.configured')
    set_state('ngxps.reload')


@when('config.changed.tmpfs_size')
def create_tmpfs():
    hookenv.status_set('maintenance', 'creating cache')
    with ngxps.stop_start():
        ngxps.create_tmpfs(config['tmpfs_size'])

    set_state('tmpfs.ready')


@when('config.changed.dhe_size')
def create_dhe():
    hookenv.status_set('maintenance', 'creating dhe')
    with ngxps.stop_start():
        ngxps.create_dhe(config['dhe_size'])

    set_state('dhe.ready')


@when('ngxps.ready')
def update_status():
    _, message = hookenv.status_get()

    if ngxps.running():
        if not message == 'nginx running':
            hookenv.status_set('active', 'nginx running')
    else:
        if not message == 'nginx not running':
            hookenv.status_set('maintenance', 'nginx not running')


@when('ngxps.installed', 'ngxps.configured', 'dhe.ready', 'tmpfs.ready')
@when_not('ngxps.ready')
def start():
    hookenv.status_set('active', 'starting nginx')
    if ngxps.start():
        set_state('ngxps.ready')
        reset_state()
        update_status()


@when('ngxps.ready', 'ngxps.upgrade')
def upgrade():
    hookenv.status_set('active', 'upgrading nginx')
    if ngxps.upgrade():
        reset_state()
        update_status()


@when('ngxps.ready', 'ngxps.reload')
def reload():
    hookenv.status_set('active', 'reloading nginx')
    if ngxps.reload():
        reset_state()
        update_status()


@when('ngxps.ready', 'ngxps.restart')
def restart():
    hookenv.status_set('active', 'restarting nginx')
    if ngxps.restart():
        reset_state()
        update_status()


@when('ngxps.ready')
@when_not('web-engine.available')
def disable_nginx():
    if not data_changed('web-engine.contexts', {}):
        return

    if len(ngxps.enabled_sites()) == 0:
        return

    ngxps.enable_sites('')

    set_state('ngxps.reload')


@when('ngxps.ready', 'web-engine.available')
def add_sites(webengine):
    for context in webengine.contexts():
        hookenv.log(context)

    if not data_changed('web-engine.contexts', webengine.contexts()):
        return

    sites = []

    for context in webengine.contexts():
        ngxps.add_site(context)

        sites.append(context['service_name'])

    ngxps.enable_sites(*sites)
    set_state('ngxps.reload')
