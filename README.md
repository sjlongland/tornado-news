TornadoNews: a feed aggregator built on Tornado
===============================================

TornadoNews is a small feed aggregator much like
[Planet](http://www.planetplanet.org/) written to be small and simple.

It uses the [Tornado](http://tornadoweb.org/) asynchronous framework to fetch
RSS and ATOM feeds asynchronously and uses its templating engine to generate
the final HTML output.  Like Planet, it is intended to be run from a `cron`
job, with the output served up by a conventional HTTP server (e.g. Apache,
nginx, lighthttpd, OpenBSD httpd, Microsoft IIS, etc...).

Feeds are parsed using the [feedparser](https://pypi.python.org/pypi/feedparser/)
module, and a composite RSS feed is generated using
[feedgenerator](https://pypi.python.org/pypi/feedgenerator).

The code works on both Python 2.7 and 3.4.  It has been exclusively developed
and tested on Linux.  It should work with anything that understands POSIX.


Contributing
----------

Pull requests on GitHub are most welcome.
Please always create them on a separate branch
so that we can rebase the merge to `master`;
this helps keep the commit history on the `master` branch
clean and noise-free.
Thanks in advance!
