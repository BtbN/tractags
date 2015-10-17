# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

extra = {}

try:
    from trac.util.dist  import  get_l10n_cmdclass
    cmdclass = get_l10n_cmdclass()
    if cmdclass:
        extra['cmdclass'] = cmdclass
        extractors = [
            ('**.py',                'python', None),
            ('**/templates/**.html', 'genshi', None),
        ]
        extra['message_extractors'] = {
            'tractags': extractors,
        }
# i18n is implemented to be optional here
except ImportError:
    pass


setup(
    name='TracTags',
    version='0.9',
    packages=find_packages(exclude=['*.tests']),
    package_data={'tractags' : [
        'templates/*.html', 'htdocs/js/*.js', 'htdocs/css/*.css',
        'htdocs/images/*.png', 'locale/*/LC_MESSAGES/*.mo',
        'locale/.placeholder']},
    # With acknowledgement to Muness Albrae for the original idea :)
    # With acknowledgement to Dmitry Dianov for input field auto-completion.
    author='Alec Thomas',
    author_email='alec@swapoff.org',
    license='BSD',
    url='http://trac-hacks.org/wiki/TagsPlugin',
    description='Tags plugin for Trac',
    install_requires=['Trac'],
    extras_require={
        'babel': 'Babel>= 0.9.5',
        'tracrpc': 'TracXMLRPC >= 1.1.0'},
    entry_points = {'trac.plugins': [
        'tractags = tractags',
        'tractags.xmlrpc = tractags.xmlrpc[tracrpc]']},
    test_suite = 'tractags.tests.test_suite',
    tests_require = [],
    **extra
    )
