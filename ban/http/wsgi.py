import re
from datetime import timezone
from functools import wraps

from dateutil.parser import parse as parse_date
from flask import Flask, make_response
from flask_cors import CORS
from werkzeug.routing import BaseConverter, ValidationError

from ban.core import context
from ban.core.encoder import dumps
from ban.db import database

from .schema import Schema


class App(Flask):
    _schema = Schema()

    def jsonify(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            rv = func(*args, **kwargs)
            if not isinstance(rv, tuple):
                rv = [rv]
            else:
                rv = list(rv)
            rv[0] = dumps(rv[0], sort_keys=True)
            resp = make_response(tuple(rv))
            resp.mimetype = 'application/json'
            return resp
        return wrapper

    def endpoint(self, *paths, **kwargs):
        if not paths:
            paths = ['/']

        def wrapper(func):
            func._endpoint = (paths, kwargs)
            return func

        return wrapper

    def resource(self, cls):
        if hasattr(cls, 'model'):
            self._schema.register_model(cls.model)
        instance = cls()
        for name in dir(cls):
            func = getattr(instance, name)
            if hasattr(func, '_endpoint'):
                self.register_endpoint(func)
        return cls

    def register_endpoint(self, func):
        from .auth import auth
        cls = func.__self__.__class__
        paths, kwargs = func._endpoint
        scopes = []
        if kwargs['methods'] != ['GET']:
            scopes = ['{}_write'.format(cls.__name__.lower())]
        func = auth.require_oauth(*scopes)(func)
        for path in paths:
            path = '{}{}'.format(cls.endpoint, path)
            endpoint = ('{}-{}'.format(cls.__name__, func.__name__)
                               .lower().replace('_', '-'))
            self.add_url_rule(path, view_func=func, endpoint=endpoint,
                              strict_slashes=False, **kwargs)
            path = re.sub(r'<(\w+:)?(\w+)>', r'{\2}', path)
            self._schema.register_endpoint(path, func, kwargs['methods'], cls)


class DateTimeConverter(BaseConverter):

    def to_python(self, value):
        try:
            value = parse_date(value)
        except ValueError:
            raise ValidationError
        # Be smart, imply that naive dt are in the same tz the API
        # exposes, which is UTC.
        if not value.tzinfo:
            value = value.replace(tzinfo=timezone.utc)
        return value


app = application = App(__name__)
CORS(app)
app.url_map.converters['datetime'] = DateTimeConverter


@app.errorhandler(404)
@app.jsonify
def page_not_found(error):
    return {'error': 'Path not found'}, 404


@app.errorhandler(405)
@app.jsonify
def method_not_allowed(error):
    return {'error': 'Method not allowed'}, 405


@app.before_request
def connect_db():
    database.connect()


@app.teardown_request
def close_db(exc):
    if not database.is_closed():
        database.close()
