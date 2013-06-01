import os
import sys
import yum
import glob
from datetime import datetime
import multiprocessing

class StockpileYumBase(yum.YumBase):

    def __init__(self):
        yum.YumBase.__init__(self)
        self.preconf = yum._YumPreBaseConf()
        self.preconf.debuglevel = 0
        self.prerepoconf = yum._YumPreRepoConf()
        self.setCacheDir(force=True, reuse=False, tmpdir=yum.misc.getCacheDir())
        self.repos.repos = {}

class Stockpile:

    class Log:

        @staticmethod
        def write(message):
            print message

        @staticmethod
        def debug(message):
            Stockpile.Log.write('debug: %s' % message)

        @staticmethod
        def info(message):
            Stockpile.Log.write('info: %s' % message)

    @staticmethod
    def get_yum():
        yb = StockpileYumBase()
        return yb

    @staticmethod
    def get_repo_version():
        now = datetime.now()
        return '%s-%s-%s' % (now.month, now.day, now.year)

    @staticmethod
    def get_repo_dir(basedir, name):
        return '%s/%s' % (basedir, name)

    @staticmethod
    def get_packages_dir(repodir):
        return '%s/packages' % repodir

    @staticmethod
    def get_versioned_dir(repodir, version):
        return '%s/%s' % (repodir, version)

    @staticmethod
    def get_latest_symlink_path(repodir):
        return '%s/latest' % repodir

    @staticmethod
    def get_package_symlink_path(versioned_dir, pkg_file):
        return '%s/%s' % (versioned_dir, pkg_file)

    @staticmethod
    def get_package_symlink_target(pkg_file):
        return '../packages/%s' % pkg_file

    @staticmethod
    def get_package_filename(pkg):
        return '%s-%s-%s.%s.rpm' % (pkg.name, pkg.version, pkg.release, pkg.arch)

    @staticmethod
    def validate_basedir(basedir):
        if type(basedir) is not str:
            raise StockpileException('basedir must be a string')

    @staticmethod
    def validate_basedirs(basedirs):
        if type(basedirs) is not list:
            raise StockpileException('basedirs must be a list')
        for basedir in basedirs:
            Stockpile.validate_basedir(basedir)

    @staticmethod
    def validate_mirrorlist(mirrorlist):
        if type(mirrorlist) is not str:
            raise StockpileException('mirrorlist must be a string')
        if not mirrorlist.start_with('http'):
            raise StockpileException('mirror lists must start with "http"')

    @staticmethod
    def validate_repos(repos):
        if type(repos) is not list:
            raise StockpileException('repos must be a list')

    @staticmethod
    def validate_repofiles(repofiles):
        if type(repofiles) is not list:
            raise StockpileException('repofiles must be a list')

    @staticmethod
    def validate_repodirs(repodirs):
        if type(repodirs) is not list:
            raise StockpileException('repodirs must be a list')

    @staticmethod
    def validate_arch(arch):
        if arch not in ['i386', 'i486', 'i586', 'i686', 'x86_64', 'noarch']:
            raise StockpileException('Invalid architecture "%s"' % arch)

    @staticmethod
    def validate_arch_list(arch_list):
        if type(arch_list) is not list:
            raise StockpileException('architecture[s] must be a list')
        for arch in arch_list:
            Stockpile.validate_arch(arch)

    @staticmethod
    def make_dir(dir):
        if not os.path.exists(dir):
            Stockpile.Log.debug('Creating directory %s' % dir)
            os.makedirs(dir)

    @staticmethod
    def symlink(path, target):
        if not os.path.islink(path):
            if os.path.isfile(path):
                raise StockpileException('%s is a file - Cannot create symlink' % path)
            dir = os.path.dirname(path)
            if not os.path.exists(dir):
                Stockpile.make_dir(dir)
        elif os.readlink(path) != target:
            Stockpile.Log.debug('Unlinking %s because it is outdated' % path)
            os.unlink(path)
        if not os.path.lexists(path):
            Stockpile.Log.debug('Linking %s to %s' % (path, target))
            os.symlink(target, path)

    @staticmethod
    def repo(name, arch=None, baseurls=None, mirrorlist=None):
        yb = Stockpile.get_yum()
        if baseurls is not None:
            Stockpile.validate_baseurls(baseurls)
            repo = yb.add_enable_repo(name, baseurls=baseurls)
        if mirrorlist is not None:
            Stockpile.validate_mirrorlist(mirrorlist)
            repo = yb.add_enable_repo(name, mirrorlist=mirrorlist)
        if arch is not None:
            Stockpile.validate_arch_list(arch)
            yb.doSackSetup(thisrepo=name, archlist=arch)

        return repo

    @staticmethod
    def set_repo_path(repo, path):
        if type(repo) is not yum.yumRepo.YumRepository:
            raise StockpileException('Repo must be a yum.yumRepo.YumRepository instance')
        repo.pkgdir = path
        return repo

    @staticmethod
    def sync(basedir, repos=[], repofiles=[], repodirs=[]):
        Stockpile.validate_basedir(basedir)
        Stockpile.validate_repos(repos)
        Stockpile.validate_repofiles(repofiles)
        Stockpile.validate_repodirs(repodirs)

        for file in repofiles:
            for filerepo in Stockpile.repos_from_file(file):
                repos.append(filerepo)

        for dir in repodirs:
            for dirrepo in Stockpile.repos_from_dir(dir):
                repos.append(dirrepo)

        version = Stockpile.get_repo_version()

        processes = []
        for repo in repos:
            dest = Stockpile.get_repo_dir(basedir, repo.id)
            p = multiprocessing.Process(target=Stockpile.sync_repo, args=(repo, dest, version))
            p.start()
            processes.append(p)

        complete_count = 0
        while True:
            for p in processes:
                if not p.is_alive():
                    complete_count += 1
            if complete_count == len(processes):
                break

    @staticmethod
    def sync_repo(repo, dest, version):
        yb = Stockpile.get_yum()

        packages_dir = Stockpile.get_packages_dir(dest)
        versioned_dir = Stockpile.get_versioned_dir(dest, version)
        latest_symlink = Stockpile.get_latest_symlink_path(dest)

        repo = Stockpile.set_repo_path(repo, packages_dir)
        yb.repos.add(repo)
        yb.repos.enableRepo(repo.id)

        packages = []
        for package in yb.doPackageLists(pkgnarrow='available', showdups=False):
            packages.append(package)

        Stockpile.Log.info('Syncing %d packages from repository %s' % (len(packages), repo.id))
        yb.downloadPkgs(packages)
        Stockpile.Log.info('Finished downloading packages from repository %s' % repo.id)

        Stockpile.make_dir(versioned_dir)

        for pkg in packages:
            pkg_file = Stockpile.get_package_filename(pkg)
            symlink = Stockpile.get_package_symlink_path(versioned_dir, pkg_file)
            link_to = Stockpile.get_package_symlink_target(pkg_file)

            Stockpile.symlink(symlink, link_to)

        Stockpile.symlink(latest_symlink, version)

    @staticmethod
    def repos_from_file(path):
        if not os.path.exists(path):
            raise StockpileException('No such file or directory: %s' % path)
        yb = Stockpile.get_yum()
        yb.getReposFromConfigFile(path)
        for repo in yb.repos.findRepos('*'):
            yb.doSackSetup(thisrepo=repo.getAttribute('name'))
        repos = []
        for repo in yb.repos.findRepos('*'):
            if repo.isEnabled():
                Stockpile.Log.info('Added repo %s from file %s' % (repo.id, path))
                repos.append(repo)
            else:
                Stockpile.Log.debug('Not adding repo %s because it is disabled' % repo.id)
        return repos

    @staticmethod
    def repos_from_dir(path):
        repos = []
        if os.path.isdir(path):
            for file in sorted(glob.glob('%s/*.repo' % path)):
                for repo in Stockpile.repos_from_file(file):
                    repos.append(repo)
        return repos


class StockpileException(Exception):

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return repr(self.message)


if __name__ == '__main__':

    from optparse import OptionParser

    parser = OptionParser()
    parser.add_option('--dest', dest='dest')
    parser.add_option('-d', '--repodir', action='append', default=[])
    parser.add_option('-f', '--repofile', action='append', default=[])
    options, args = parser.parse_args()

    if not options.dest:
        print '--dest is required'
        sys.exit(0)

    Stockpile.sync(options.dest, repofiles=options.repofile, repodirs=options.repodir)
