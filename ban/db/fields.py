from datetime import datetime, timezone
import json
import re

import peewee

from playhouse import postgres_ext, fields
from playhouse.fields import PasswordField as PWDField
from postgis import Point
from psycopg2.extras import DateTimeTZRange

from ban.core.exceptions import ValidationError
from . import cache

__all__ = ['PointField', 'ForeignKeyField', 'CharField', 'IntegerField',
           'HStoreField', 'UUIDField', 'ArrayField', 'DateTimeField',
           'BooleanField', 'BinaryJSONField', 'FantoirField',
           'ManyToManyField', 'PasswordField', 'DateRangeField', 'TextField',
           'CachedForeignKeyField']


lonlat_pattern = re.compile('^[\[\(]{1}(?P<lon>-?\d{,3}(:?\.\d*)?), ?(?P<lat>-?\d{,3}(\.\d*)?)[\]\)]{1}$')  # noqa


peewee.OP.update(
    BBOX2D='&&',
    BBOXCONTAINS='~',
    BBOXCONTAINED='@',
)
postgres_ext.PostgresqlExtDatabase.register_ops({
    peewee.OP.BBOX2D: peewee.OP.BBOX2D,
    peewee.OP.BBOXCONTAINS: peewee.OP.BBOXCONTAINS,
    peewee.OP.BBOXCONTAINED: peewee.OP.BBOXCONTAINED,
})

class NoIndexMixin:

	def __init__(self, *args, **kwargs):
		kwargs['index'] = False
		super().__init__(*args, **kwargs)

# TODO: mv to a third-party module.
class PointField(NoIndexMixin, peewee.Field, postgres_ext.IndexedFieldMixin):
    db_field = 'point'
    __data_type__ = Point
    # TODO how to deal properly with custom type?
    # Or should we just accept geojson (and not [lat, lon]…)?
    __schema_type__ = 'object'
    __schema_format__ = 'geojson'
    srid = 4326
    index_type = 'GiST'

    def db_value(self, value):
        return self.coerce(value)

    def python_value(self, value):
        return self.coerce(value)

    def coerce(self, value):
        if not value:
            return None
        if isinstance(value, Point):
            return value
        if isinstance(value, dict):  # GeoJSON
            value = value['coordinates']
        if isinstance(value, str):
            search = lonlat_pattern.search(value)
            if search:
                value = (float(search.group('lon')),
                         float(search.group('lat')))
        return Point(value[0], value[1], srid=self.srid)

    def contained(self, geom):
        return peewee.Expression(self, peewee.OP.BBOXCONTAINED, geom)

    def contains(self, geom):
        return peewee.Expression(self, peewee.OP.BBOXCONTAINS, geom)

    def in_bbox(self, south, north, east, west):
        return self.contained(
            peewee.fn.ST_MakeBox2D(Point(west, south, srid=self.srid),
                                   Point(east, north, srid=self.srid)),
            )


postgres_ext.PostgresqlExtDatabase.register_fields({'point':
                                                    'geometry(Point)'})


class DateRangeField(NoIndexMixin, peewee.Field):
    db_field = 'tstzrange'
    __data_type__ = datetime
    __schema_type__ = 'string'
    __schema_format__ = 'date-time'

    def db_value(self, value):
        return self.coerce(value)

    def python_value(self, value):
        return self.coerce(value)

    def coerce(self, value):
        if not value:
            value = [None, None]
        if isinstance(value, (list, tuple)):
            # '[)' means include lower bound but not upper.
            value = DateTimeTZRange(*value, bounds='[)')
        return value

    def contains(self, dt):
        return peewee.Expression(self, peewee.OP.ACONTAINS, dt)


class CachedRelationDescriptor(peewee.RelationDescriptor):

    def get_object_or_id(self, instance):
        rel_id = instance._data.get(self.att_name)
        if not rel_id:
            return rel_id
        keys = (self.rel_model.__name__, rel_id)
        return cache.cache(keys, super().get_object_or_id, instance)


class ForeignKeyField(NoIndexMixin, peewee.ForeignKeyField):

    __data_type__ = int
    __schema_type__ = 'integer'

    def coerce(self, value):
        if not value:
            return None
        if isinstance(value, dict):
            # We have a resource dict.
            value = value['id']
        if hasattr(self.rel_model, 'coerce'):
            value = self.rel_model.coerce(value)
        if isinstance(value, peewee.Model):
            value = value.pk
        return super().coerce(value)

    def _get_related_name(self):
        # cf https://github.com/coleifer/peewee/pull/844
        return (self._related_name or '{classname}_set').format(
                                        classname=self.model_class._meta.name)


class CachedForeignKeyField(ForeignKeyField):

    def _get_descriptor(self):
        return CachedRelationDescriptor(self, self.rel_model)


class CharField(NoIndexMixin, peewee.CharField):
    __data_type__ = str
    __schema_type__ = 'string'

    def __init__(self, *args, **kwargs):
        if 'format' in kwargs:
            self.regex = re.compile(kwargs.pop('format'))
        if 'length' in kwargs:
            kwargs['min_length'] = kwargs['max_length'] = kwargs.pop('length')
        self.min_length = kwargs.pop('min_length', None)
        super().__init__(*args, **kwargs)

    def coerce(self, value):
        if self.null and not value:
            return None
        return super().coerce(value)


class TextField(NoIndexMixin, peewee.TextField):
    __data_type__ = str
    __schema_type__ = 'string'

    def coerce(self, value):
        if self.null and not value:
            return None
        return super().coerce(value)


class IntegerField(NoIndexMixin, peewee.IntegerField):
    __data_type__ = int
    __schema_type__ = 'integer'

    def coerce(self, value):
        if not value:
            return None
        return super().coerce(value)


class HStoreField(NoIndexMixin, postgres_ext.HStoreField):
    __data_type__ = dict
    __schema_type__ = 'object'

    def coerce(self, value):
        if isinstance(value, str):
            value = json.loads(value)
        return super().coerce(value)


class BinaryJSONField(NoIndexMixin, postgres_ext.BinaryJSONField):
    __data_type__ = dict
    __schema_type__ = 'object'


class UUIDField(NoIndexMixin, peewee.UUIDField):
    pass


class ArrayField(NoIndexMixin, postgres_ext.ArrayField):
    __data_type__ = list
    __schema_type__ = 'array'

    def coerce(self, value):
        if not value:
            return []  # Coerce None to [].
        if value and not isinstance(value, (list, tuple)):
            value = [value]
        return value

    def python_value(self, value):
        return self.coerce(value)

    def db_value(self, value):
        if value is None:
            value = []
        return super().db_value(value)


class DateTimeField(NoIndexMixin, postgres_ext.DateTimeTZField):
    __data_type__ = datetime
    __schema_type__ = 'string'
    __schema_format__ = 'date-time'

    def python_value(self, value):
        value = super().python_value(value)
        if value:
            # PSQL store dates in the server timezone, but we only want to
            # deal with UTC ones.
            return value.astimezone(timezone.utc)


class BooleanField(NoIndexMixin, peewee.BooleanField):
    __data_type__ = bool
    __schema_type__ = 'boolean'


class FantoirField(CharField):

    max_length = 9

    def coerce(self, value):
        if not value:
            return None
        value = str(value)
        if len(value) == 10:
            value = value[:9]
        if not len(value) == 9:
            raise ValidationError('FANTOIR must be municipality INSEE + 4 '
                                  'first chars of FANTOIR, '
                                  'got `{}` instead'.format(value))
        return value


class ManyToManyField(fields.ManyToManyField):
    __data_type__ = list
    __schema_type__ = 'array'

    def __init__(self, *args, **kwargs):
        # ManyToManyField is not a real "Field", so try to better conform to
        # Field API.
        # https://github.com/coleifer/peewee/issues/794
        self.null = True
        self.unique = False
        self.index = False
        super().__init__(*args, **kwargs)

    def coerce(self, value):
        if not value:
            return []
        if not isinstance(value, (tuple, list, peewee.SelectQuery)):
            value = [value]
        value = [self.rel_model.coerce(item) for item in value]
        return super().coerce(value)

    def add_to_class(self, model_class, name):
        # https://github.com/coleifer/peewee/issues/794
        model_class._meta.fields[name] = self
        super().add_to_class(model_class, name)


class PasswordField(PWDField):

    def python_value(self, value):
        if value is None:
            return value
        return super().python_value(value)
