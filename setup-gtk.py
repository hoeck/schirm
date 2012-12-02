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
      author="Erik Soehnel",
      author_email="eriksoehnel@googlemail.com",
      url="https://github.com/hoeck/schirm",
      provides=['schirm', 'schirmclient'],
      scripts=["bin/schirmgtk"],
      packages=['schirm', 'schirm.pyte', 'schirm.ws4py'],
      package_dir={'schirm':'schirm',
                   '':'support'},
      py_modules=['schirmclient'],
      package_data={'schirm':['resources/*']},
      ext_modules=[Extension(name='schirm.webkitutils',
                             sources=['lib/webkitutils.c'],
                             extra_compile_args=pkgconfig_cflags(*libs),
                             extra_link_args=pkgconfig_libs(*libs))],
      )
