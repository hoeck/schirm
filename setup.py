#!/usr/bin/env python

from distutils.core import setup, Extension
import subprocess

def pkgconfig_libs(*packages):
    return subprocess.check_output("pkg-config --libs %s" % ' '.join(packages), shell=True).split()

def pkgconfig_cflags(*packages):
    return subprocess.check_output("pkg-config --cflags %s" % ' '.join(packages), shell=True).split()

libs = ('webkit-1.0', 'libsoup-2.4', 'glib-2.0', 'python')

setup(name='schirm',
      version='0.1',
      py_modules=['promise',
                  'schirm',
                  'webkit_wrapper',
                  'schirmclient',
                  'term',
                  'termscreen',
                  'webserver'],
      ext_modules=[Extension(name='webkitutils',
                             sources=['webkitutils.c'],
                             extra_compile_args=pkgconfig_cflags(*libs),
                             extra_link_args=pkgconfig_libs(*libs))],
      )






# {'define_macros': [('version_info', "(1, 3, 0, 'final', 0)"),
#                    ('__version__', '1.3.0')],
#  'extra_compile_args': ['-DBIG_JOINS=1',
#                         '-fno-strict-aliasing',
#                         '-DUNIV_LINUX',
#                         '-DUNIV_LINUX'],
#  'extra_objects': [],
#  'include_dirs': ['/usr/include/mysql'],
#  'libraries': ['mysqlclient_r'],
#  'library_dirs': ['/usr/lib/mysql'],
#  'name': '_mysql'}

