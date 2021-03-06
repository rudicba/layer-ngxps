""" Nginx pagespeed utils
"""
import os
import hashlib

from contextlib import contextmanager
from shutil import rmtree, copyfile
from subprocess import check_call, DEVNULL

from charmhelpers.core import host, hookenv
from charmhelpers.core.templating import render


from charms.reactive.helpers import any_file_changed, data_changed


def install(src):
    """ Install nginx from .deb file

    Retuns:
        True if new installation, False otherwise
    """
    new_version = False
    dst_folder = '/root/packages'
    host.mkdir(dst_folder, owner='root', group='root')

    dst = os.path.join(dst_folder, os.path.basename(src))
    copyfile(src, dst)

    if any_file_changed([dst]):
        new_version = True
        check_call(['dpkg', '-i', dst])

    host.mkdir('/usr/local/nginx/logs', owner='root', group='root')
    host.mkdir('/usr/local/nginx/temp', owner='root', group='root')

    return new_version


def configure():
    """ Render all basic files needed by nginx pagespeed with naxsi support for
    running.

    Return:
        True if any file changed, otherwise False
    """
    config = hookenv.config()

    render('conf/nginx.conf.j2', '/usr/local/nginx/conf/nginx.conf',
           config, owner='root', group='root')

    render('conf/ssl.conf.j2', '/usr/local/nginx/conf/ssl.conf',
           config, owner='root', group='root')

    render('conf/pagespeed.conf.j2', '/usr/local/nginx/conf/pagespeed.conf',
           config, owner='root', group='root')

    render('conf/naxsi_core.rules.j2',
           '/usr/local/nginx/conf/naxsi_core.rules',
           config, owner='root', group='root')

    return any_file_changed([
        '/usr/local/nginx/conf/nginx.conf',
        '/usr/local/nginx/conf/ssl.conf',
        '/usr/local/nginx/conf/pagespeed.conf',
        '/usr/local/nginx/conf/naxsi_core.rules'
    ])


def set_cache(context={}):
    """Render cache config.

    Return:
        True if new memcache is render
    """

    hookenv.log(context)

    render('conf/cache.conf.j2', '/usr/local/nginx/conf/cache.conf',
           context, owner='root', group='root')

    return any_file_changed([
        '/usr/local/nginx/conf/cache.conf',
    ])


def validate_config():
    """Return true is nginx configuration is valid
    """
    ret_code = check_call(['/usr/local/nginx/sbin/nginx', '-t'])
    return ret_code == 0


def create_tmpfs(tmpfs_size):
    """ Create and mount tmp filesystem of desired size
    """
    cache_path = '/var/ngx_pagespeed_cache'
    host.mkdir(cache_path, owner='nobody', group='nogroup')

    opts_tmpl = 'rw,uid={user},gid={group},size={size}m,mode=0775,noatime'
    opts = opts_tmpl.format(size=tmpfs_size, user='nobody', group='nogroup')

    host.fstab_remove(cache_path)
    host.fstab_add('tmpfs', cache_path, 'tmpfs', options=opts)

    for mount in host.mounts():
        if mount[0] == cache_path:
            host.umount(cache_path)

    host.fstab_mount(cache_path)


def create_dhe(dhe_size):
    """ Create Diffie-Hellman key for SSL settings
    """
    env = {'RANDFILE': '/root/.rnd'}
    host.mkdir('/usr/local/nginx/ssl', owner='root', group='root')
    openssl_cmd = ['openssl', 'dhparam', '-out',
                   '/usr/local/nginx/ssl/dhparams.pem', str(dhe_size)]

    check_call(openssl_cmd, env=env, stdout=DEVNULL)


def add_site(context):
    """ Given context render all neccesaries files for site
    """
    sites_enabled = '/usr/local/nginx/conf/sites-enabled'
    conf_folder = os.path.join(sites_enabled, context['service_name'])
    host.mkdir(conf_folder)

    naxsi_rules = os.path.join(conf_folder, 'naxsi.rules')
    pagespeed_conf = os.path.join(conf_folder, 'pagespeed.conf')
    site_conf = os.path.join(conf_folder, 'site.conf')

    render('sites/naxsi.rules.j2', naxsi_rules, context)
    render('sites/pagespeed.conf.j2', pagespeed_conf, context)
    render('sites/site.conf.j2', site_conf, context)


def enable_sites(*sites):
    """ Enable all sites in sites list and disable any site not in list

    return true if any file change, false otherwise
    """
    sites_enabled = '/usr/local/nginx/conf/sites-enabled'
    sites_files = {}

    if not os.path.isdir(sites_enabled):
        return

    for f_path in os.listdir(sites_enabled):
        if f_path not in sites:
            rmtree(os.path.join(sites_enabled, f_path))

    for path, subdirs, files in os.walk(sites_enabled):
        for name in files:
            conf_path = os.path.join(path, name)
            md5 = hashlib.md5(open(conf_path, 'rb').read()).hexdigest()
            sites_files[conf_path] = md5

    return data_changed('ngxps.sites_files', sites_files)


def enabled_sites():
    sites_enabled = '/usr/local/nginx/conf/sites-enabled'

    sites = []

    if not os.path.isdir(sites_enabled):
        return sites

    for f_path in os.listdir(sites_enabled):
        sites.append(f_path)

    return sites


def no_sites():
    return len(enabled_sites()) == 0


def conf_files():
    conf = '/usr/local/nginx/conf/'
    files = []

    for path, _, names in os.walk(conf):
        for name in names:
            files.append(os.path.join(path, name))

    return files


def enable():
    if host.init_is_systemd():
        render('systemd/nginx.service.j2', '/etc/systemd/system/nginx.service',
               {}, owner='root', group='root', perms=0o755)
    else:
        render('init.d/nginx.j2', '/etc/init.d/nginx',
               {}, owner='root', group='root', perms=0o755)


def disable():
    if host.init_is_systemd():
        systemd = '/etc/systemd/system/nginx.service'
        if os.path.isfile(systemd):
            os.remove(systemd)
    else:
        initd = '/etc/init.d/nginx'
        if os.path.isfile(initd):
            os.remove(initd)


def stop():
    return host.service_stop('nginx')


def start():
    return host.service_start('nginx')


def restart():
    return host.service_restart('nginx')


def reload():
    return host.service_reload('nginx')


def upgrade():
    return host.service('upgrade', 'nginx')


def running():
    return host.service_running('nginx')


@contextmanager
def stop_start():
    is_running = running()
    if is_running:
        stop()
    yield
    if is_running:
        start()
