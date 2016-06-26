import os
import tarfile
from subprocess import check_call, DEVNULL, CalledProcessError

from contextlib import contextmanager
from shutil import rmtree, copyfile

from charmhelpers.core import host, unitdata, hookenv
from charmhelpers.core.templating import render
from charmhelpers.fetch import apt_install


config = hookenv.config()

packages = ['build-essential', 'zlib1g-dev', 'libssl-dev', 'libpcre3',
            'libpcre3-dev', 'unzip', 'geoip-database', 'wget', 'libgeoip1',
            'libgeoip-dev']

build_path = '/root/build'

build_opts = [
        '--with-http_ssl_module',
        '--with-http_gzip_static_module',
        '--without-mail_pop3_module',
        '--without-mail_smtp_module',
        '--without-mail_imap_module',
        '--with-http_geoip_module',
    ]


def extract(tar, destination):
    tarfile.open(tar, 'r:gz').extractall(path=destination)
    return os.path.join(destination, tar_root(tar))


def tar_root(tar):
    return tarfile.open(tar, 'r:gz').getnames()[0]


def install(nginx, nps, psol, naxsi):
    db = unitdata.kv()

    required = {
        'nginx': tar_root(nginx),
        'nps': tar_root(nps),
        'psol': tar_root(psol),
        'naxsi': tar_root(naxsi),
    }
    installed = db.get('installed', default={})

    if required == installed:
        return False

    if os.path.isdir(build_path):
        rmtree(build_path)

    nginx_src = extract(nginx, build_path)
    nps_src = extract(nps, build_path)
    naxsi_src = extract(naxsi, build_path)
    extract(psol, nps_src)

    apt_install(packages)

    with host.chdir(nginx_src):
        try:
            configure_cmd = [
                './configure', '--add-module={}'.format(nps_src),
                '--add-module={}'.format(os.path.join(naxsi_src, 'naxsi_src')),
            ] + build_opts
            check_call(configure_cmd, stdout=DEVNULL)
            check_call(['make'], stdout=DEVNULL)
            check_call(['make', 'install'], stdout=DEVNULL)
        except CalledProcessError:
            raise  # handle errors in the called executable
        except OSError:
            raise  # executable not found

    # Copy default naxsi rules from naxsi sources to nginx
    copyfile(os.path.join(naxsi_src, 'naxsi_config', 'naxsi_core.rules'),
             '/usr/local/nginx/conf/naxsi_core.rules')

    db.set('installed', required)

    return True


def configure():
    render('conf/nginx.conf.j2', '/usr/local/nginx/conf/nginx.conf',
           config, owner='root', group='root')

    render('conf/ssl.conf.j2', '/usr/local/nginx/conf/ssl.conf',
           config, owner='root', group='root')

    render('conf/pagespeed.conf.j2', '/usr/local/nginx/conf/pagespeed.conf',
           config, owner='root', group='root')


def create_tmpfs(tmpfs_size):
    cache_path = '/var/ngx_pagespeed_cache'
    host.mkdir(cache_path, owner='nobody', group='nogroup')

    options = 'rw,uid={user},gid={group},size={size}m,mode=0775,noatime'.format(
        size=tmpfs_size, user='nobody', group='nogroup')

    host.fstab_remove(cache_path)
    host.fstab_add('tmpfs', cache_path, 'tmpfs', options=options)

    for mount in host.mounts():
        if mount[0] == cache_path:
            host.umount(cache_path)

    host.fstab_mount(cache_path)


def create_dhe(dhe_size):
    env = {'RANDFILE': '/root/.rnd'}
    host.mkdir('/usr/local/nginx/ssl', owner='root', group='root')
    openssl_cmd = ['openssl', 'dhparam', '-out',
                   '/usr/local/nginx/ssl/dhparams.pem', str(dhe_size)]

    check_call(openssl_cmd, env=env, stdout=DEVNULL)


def add_site(context):
    site_conf = os.path.join('/usr/local/nginx/conf/sites-enabled',
                             context['service_name'])
    host.mkdir(site_conf)

    render('sites/naxsi.rules.j2',
           os.path.join(site_conf, 'naxsi.rules'), context)
    render('sites/pagespeed.conf.j2',
           os.path.join(site_conf, 'pagespeed.conf'), context)
    render('sites/site.conf.j2',
           os.path.join(site_conf, 'site.conf'), context)


def enable_sites(*sites):
    sites_enabled = '/usr/local/nginx/conf/sites-enabled'
    if not os.path.isdir(sites_enabled):
        return

    for f_path in os.listdir(sites_enabled):
        if f_path not in sites:
            rmtree(os.path.join(sites_enabled, f_path))


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

    for path, subdirs, names in os.walk(conf):
        for name in names:
            files.append(os.path.join(path, name))

    return files


def enable():
    render('init.d/nginx.j2', '/etc/init.d/nginx',
           {}, owner='root', group='root', perms=0o755)


def disable():
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
