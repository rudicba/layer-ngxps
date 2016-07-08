""" Nginx pagespeed installer and manager
"""
import os
import platform
import tarfile

from contextlib import contextmanager
from shutil import rmtree, copyfile
from subprocess import check_call, DEVNULL

from charmhelpers.core import host, hookenv
from charmhelpers.core.templating import render
from charmhelpers.fetch import apt_install

from charms.reactive.helpers import any_file_changed


PACKAGES = ['build-essential', 'zlib1g-dev', 'libssl-dev', 'libpcre3',
            'libpcre3-dev', 'unzip', 'geoip-database', 'wget', 'libgeoip1',
            'libgeoip-dev', 'checkinstall']

BUILD_PATH = '/root/build'

BUILD_OPTS = [
    '--with-http_ssl_module',
    '--with-http_gzip_static_module',
    '--without-mail_pop3_module',
    '--without-mail_smtp_module',
    '--without-mail_imap_module',
    '--with-http_geoip_module',
    '--http-client-body-temp-path=/usr/local/nginx/temp/body',
    '--http-fastcgi-temp-path=/usr/local/nginx/temp/fastcgi',
    '--http-proxy-temp-path=/usr/local/nginx/temp/proxy',
    '--http-scgi-temp-path=/usr/local/nginx/temp/scgi',
    '--http-uwsgi-temp-path=/usr/local/nginx/temp/uwsgi',
]


def extract(tar, destination):
    """ Extract tar.gz file into destination, return path to extracted file
    up a directory
    """
    tarfile.open(tar, 'r:gz').extractall(path=destination)
    return os.path.join(destination, tar_root(tar))


def tar_root(tar):
    """ Return name of root directory of tar.gz file
    """
    return tarfile.open(tar, 'r:gz').getnames()[0]


def build_sources(nginx, nps, psol, naxsi):
    """ Build nginx with pagespeed and naxsi modules
    """
    release = '1'
    arch = 'amd64' if platform.machine() == 'x86_64' else 'i386'

    if os.path.isdir(BUILD_PATH):
        rmtree(BUILD_PATH)

    nginx_src = extract(nginx, BUILD_PATH)
    nps_src = extract(nps, BUILD_PATH)
    naxsi_src = extract(naxsi, BUILD_PATH)
    extract(psol, nps_src)

    version = os.path.basename(os.path.normpath(nginx_src)).split('-', 1)[1]

    apt_install(PACKAGES)

    with host.chdir(nginx_src):
        configure_cmd = [
            './configure', '--add-module={}'.format(nps_src),
            '--add-module={}'.format(os.path.join(naxsi_src, 'naxsi_src')),
        ] + BUILD_OPTS
        check_call(configure_cmd, stdout=DEVNULL)
        check_call(['make'], stdout=DEVNULL)
        check_call(['checkinstall',
                    '--install=yes',
                    '--fstrans=no',
                    '--pkgname=nginx',
                    '--pkgversion={}'.format(version),
                    '--pkgrelease={}'.format(release),
                    '--pkgarch={}'.format(arch),
                    '-y', 'make', 'install'])

        deb = '{name}_{version}-{release}_{arch}'

    return os.path.join(nginx_src, deb)


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
    """ Enable all sites in listed in sites, disable any site not in list
    """
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

    for path, _, names in os.walk(conf):
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
