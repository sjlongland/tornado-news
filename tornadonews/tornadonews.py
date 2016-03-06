#!/usr/bin/env python

"""
TornadoNews: Simple RSS/Atom aggregator written in Tornado.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
"""

from tornado.template import Template
from tornado.httpclient import AsyncHTTPClient
from tornado.ioloop import IOLoop
import feedparser
import yaml
import argparse
from calendar import timegm
from functools import partial
import logging
from multiprocessing.pool import ThreadPool
from multiprocessing import cpu_count
from os import makedirs, path, stat
from hashlib import sha1
import feedgenerator
from six import StringIO, text_type, binary_type, PY3
import datetime

if PY3:
    # Doesn't seem to work in Python 3.  Until further notice, let's
    # disable this for now.
    # http://blog.yjl.im/2013/12/workaround-of-libxml2-unsupported.html
    feedparser.PREFERRED_XML_PARSERS.remove('drv_libxml2')


class FeedEntry(object):
    """
    FeedEntry: a simple object for storing the specifics of an article
    so that they can be grouped and sorted.
    """

    def __init__(self, source, entry_id, link, title, author,
            updated, content):
        """
        Construct a new FeedEntry object.
        """

        self._source    = text_type(source)
        self._id        = text_type(entry_id)
        self._author    = text_type(author)
        self._anchor    = None
        self._link      = text_type(link)
        self._title     = text_type(title)
        self._updated   = float(updated)
        self._content   = text_type(content)

    @classmethod
    def from_entry(cls, source, entry):
        """
        Parse the feedparser-generated entry dict and return a FeedEntry
        object from it.
        """
        return cls(
                source, entry['id'], entry['link'], entry['title'],
                entry.get('author') or 'Anonymous',
                timegm(entry.get('updated_parsed') or \
                        entry['published_parsed']),
                entry.get('content') or entry['summary'])

    @property
    def raw(self):
        """
        Dump the feed entry so that it can be serialised safely and
        later returned.
        """
        return {
                'source': self.source,
                'entry_id': self.id,
                'link': self.link,
                'title': self.title,
                'author': self.author,
                'updated': self.updated,
                'content': self.content,
        }

    @property
    def source(self):
        return self._source

    @property
    def id(self):
        return self._id
    
    @property
    def anchor(self):
        if self._anchor is None:
            self._anchor = sha1(self.id.encode('UTF-8')).hexdigest()
        return self._anchor

    @property
    def title(self):
        return self._title

    @property
    def author(self):
        return self._author

    @property
    def link(self):
        return self._link

    @property
    def updated(self):
        return self._updated

    @property
    def content(self):
        return self._content

    def __lt__(self, other):
        if not isinstance(other, FeedEntry):
            return NotImplemented
        return self.updated < other.updated

    def __unicode__(self):
        return u'[%s] %s' % (self.source, self.title)

    if PY3: # Python 3
        def __str__(self):
            return self.__unicode__()
    else:  # Python 2
        def __str__(self):
            return self.__unicode__().encode('utf8')

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self)


class FeedFetcher(object):
    """
    FeedFetcher: A simplified RSS/Atom feed retriever and parser.  This
    uses Tornado's asynchronous HTTP client to retrieve the individual
    feeds as they're fed into the object using the fetch method.

    When the caller is done, they call collate, giving a callback function
    that receives the collated list at the end.
    """

    def __init__(self, cache=None, num_workers=None, io_loop=None):
        if io_loop is None:
            io_loop = IOLoop.current()

        if num_workers is None:
            num_workers = cpu_count()

        self._io_loop = io_loop
        self._log     = logging.getLogger(self.__class__.__name__)
        self._client  = AsyncHTTPClient()
        self._cache   = cache
        self._entries = []
        self._pending = set()
        self._fetched = False
        self._pool    = ThreadPool(processes=num_workers)
        self._on_done = None

    @property
    def entries(self):
        return list(self._entries)

    def fetch(self, name, url):
        """
        Fetch the feed named 'name', at the address, 'url'.
        """

        self._log.info('Retrieving %s (%s)', name, url)
        self._fetched = False
        self._pending.add(url)

        cache_dir = self._get_dir_for_url(url)
        if (cache_dir is not None) and path.isdir(cache_dir):
            if_modified_since=stat(path.join(cache_dir, 'body')).st_mtime
        else:
            if_modified_since=None

        self._client.fetch(url,
                callback=partial(self._on_get_done, name,
                    url, cache_dir),
                if_modified_since=if_modified_since)

    def _get_dir_for_url(self, url):
        if self._cache is None:
            return None

        url_hash = sha1(url.encode('UTF-8')).hexdigest()
        return path.join(
                self._cache, url_hash[0:2], url_hash[2:4], url_hash[4:])

    def _on_get_done(self, name, url, cache_dir, response):
        self._log.info('Finished retrieving %s (%s), result %s',
                name, url, response.reason)
        try:
            if response.code == 304: # Not modified
                # Read from cache
                self._log.info('Not modified, read from cache')
                body = open(path.join(cache_dir, 'body'),'rb').read()
                cached = True
                self._log.debug('Body type: %s (cache)', type(body))

            else:
                # Check for exceptions
                response.rethrow()

                # Grab body data
                body = response.body
                cached = False
                self._log.debug('Body type: %s (http)', type(body))

            # Dump to cache
            if cache_dir is not None:
                if not path.isdir(cache_dir):
                    makedirs(cache_dir)
                # Write out headers
                yaml.safe_dump(dict(response.headers),
                        stream=open(path.join(cache_dir,
                            'headers.yml'),'w'),
                        default_flow_style=False)
                # Write out raw body
                open(path.join(cache_dir, 'body'),'wb').write(body)

            # Hand off to thread pool
            self._pool.apply_async(self._process,
                    args=(name, url, body, cache_dir, cached))
        except:
            self._log.exception('Failed to process feed %s (%s)',
                    name, url)
            self._mark_done(url)

    def _process(self, name, url, body, cache_dir, cached):
        self._log.info('Processing feed %s', name)
        try:
            entries_cache = path.join(cache_dir, 'entries.yml')
            entries = None
            try:
                if cached and path.isfile(entries_cache):
                    entries = list(map(lambda e : FeedEntry(**e),
                            list(yaml.safe_load(
                                open(entries_cache,'r')))))
            except:
                self._log.debug('Failed to read cache, ignoring',
                        exc_info=1)
                cached = False

            if entries is None:
                parsed = feedparser.parse(body)

                # Extract the entries from the feed
                entries = list(map(partial(FeedEntry.from_entry, name),
                    parsed['entries']))

            if not cached and (cache_dir is not None):
                cache_out = yaml.safe_dump([e.raw for e in entries])
                open(entries_cache,'wb').write(cache_out.encode('UTF-8'))
        except:
            self._log.exception('Failed to process feed %s (%s)',
                    name, url)
            entries = None

        # Hand back to main loop
        self._io_loop.add_callback(self._mark_done, url, entries)

    def _mark_done(self, url, entries=None):
        self._log.info('%s parsed', url)
        if entries is not None:
            self._entries.extend(entries)
        self._pending.discard(url)
        self._io_loop.add_callback(self._check_finished)

    def _check_finished(self):
        self._log.debug('Fetched? %s  Pending: %s',
                self._fetched, self._pending)
        if self._fetched and not bool(self._pending):
            self._io_loop.add_callback(self._emit)

    def collate(self, callback=None):
        """
        Wait for all feeds to be loaded, then collate the resulting
        entries together for display.
        """
        # No more to fetch after this.
        self._fetched = True
        self._io_loop.add_callback(self._check_finished)
        self._log.info('Waiting for fetch to complete')
        self._on_done = callback

    def _emit(self):
        self._log.info('Collating results')
        self._entries.sort(key=lambda e : e.updated, reverse=True)
        if self._on_done is not None:
            self._io_loop.add_callback(self._on_done, list(self._entries))


class FeedEmitter(object):
    """
    FeedEmitter: Simple news item aggregator and emitter.  This takes a
    list of FeedEntry objects and optionally, some HTML templates.  The
    make_rss and make_html methods then generate RSS or HTML from these
    feed items.
    """

    def __init__(self, entries, html_base=None, html_entry=None):
        self._log         = logging.getLogger(self.__class__.__name__)
        self._entries     = entries
        self._html_base   = html_base
        self._html_entry  = html_entry
        self._log.info('Emitter constructed with %d entries',
                len(entries))

    def make_rss(self, **kwargs):
        self._log.info('Emitting RSS')
        rss = feedgenerator.Rss201rev2Feed(**kwargs)
        for entry in self._entries:
            rss.add_item(
                    title=u'[%s] %s' % (entry.source, entry.title),
                    link=entry.link,
                    description=entry.content,
                    author_name=entry.author,
                    pubdate=datetime.datetime.fromtimestamp(entry.updated),
                    unique_id=entry.id)
        out = StringIO()
        rss.write(out, 'utf-8')
        return out.getvalue()

    def make_html(self, **kwargs):
        self._log.info('Emitting HTML')
        t = Template(self._html_base)
        entries = '\n'.join(list(map(self._entry_to_html, self._entries)))
        return t.generate(entries=entries, **kwargs)

    def _entry_to_html(self, entry):
        t = Template(self._html_entry)
        return text_type(t.generate(source=entry.source,
                anchor=entry.anchor, id=entry.id,
                link=entry.link, title=entry.title,
                author=entry.author, updated=entry.updated,
                updated_str=self._date_to_str(entry.updated),
                content=entry.content), 'UTF-8')

    def _date_to_str(self, timestamp):
        return str(datetime.datetime.fromtimestamp(timestamp))


def main():
    parser = argparse.ArgumentParser(description='Feed parser/aggregator')
    parser.add_argument('config', metavar='CONFIG', type=str,
            help='Configuration file')
    args = parser.parse_args()
    cfg = yaml.load(open(args.config,'r'))
    logging.basicConfig(level=logging.DEBUG)

    ioloop = IOLoop.current()
    ioloop.add_callback(run, cfg)
    ioloop.start()

def run(cfg):
    fetcher = FeedFetcher(cache=cfg.get('cache'))
    for source in cfg['sources']:
        fetcher.fetch(**source)

    html_templates = cfg.get('html_templates',{})
    output = cfg.get('output',{})
    meta = cfg.get('meta', {})
    def emit(entries):
        try:
            emitter = FeedEmitter(entries,
                html_entry=html_templates.get('entry'),
                html_base=html_templates.get('base'))
            if output.get('html'):
                html = emitter.make_html(**meta)
                open(output['html'],'wb').write(html)
            if output.get('rss'):
                rss = emitter.make_rss(**meta)
                open(output['rss'],'w').write(rss)
        finally:
            IOLoop.current().stop()

    fetcher.collate(emit)

if __name__ == '__main__':
    main()
