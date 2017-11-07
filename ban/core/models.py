import re

import peewee
from unidecode import unidecode
from werkzeug.utils import cached_property

from ban import db
from ban.utils import compute_cia
from .versioning import Versioned, BaseVersioned
from .resource import ResourceModel, BaseResource
from .validators import VersionedResourceValidator

__all__ = ['Municipality', 'Group', 'HouseNumber', 'PostCode',
           'Position']


_ = lambda x: x


class BaseModel(BaseResource, BaseVersioned):
    pass


class Model(ResourceModel, Versioned, metaclass=BaseModel):
    resource_fields = ['version', 'created_at', 'created_by', 'modified_at',
                       'modified_by', 'attributes']
    exclude_for_collection = ['created_at', 'created_by',
                              'modified_at', 'modified_by']
    readonly_fields = (ResourceModel.readonly_fields + ['created_at',
                       'created_by', 'modified_at', 'modified_by'])

    attributes = db.HStoreField(null=True)

    class Meta:
        validate_backrefs = False
        validator = VersionedResourceValidator


class NamedModel(Model):
    name = db.CharField(max_length=200)
    alias = db.ArrayField(db.CharField, default=[], null=True)

    def __str__(self):
        return self.name


class Municipality(NamedModel):
    INSEE_FORMAT = '(2[AB]|\d{2})\d{3}'
    identifiers = ['siren', 'insee']
    resource_fields = ['name', 'alias', 'insee', 'siren', 'postcodes']
    exclude_for_version = ['postcodes']

    insee = db.CharField(length=5, unique=True, format=INSEE_FORMAT)
    siren = db.CharField(length=9, format='\d*', unique=True, null=True)

    @property
    def municipality(self):
        return self


class PostCode(NamedModel):
    resource_fields = ['code', 'name', 'alias', 'complement', 'municipality']

    complement = db.CharField(max_length=38, null=True)
    code = db.CharField(index=True, format='\d*', length=5)
    municipality = db.CachedForeignKeyField(Municipality,
                                            related_name='postcodes')

    class Meta:
        indexes = (
            (('code', 'complement', 'municipality'), True),
        )

    @property
    def housenumbers(self):
        return self.housenumber_set.order_by(
            peewee.SQL('number ASC NULLS FIRST'),
            peewee.SQL('ordinal ASC NULLS FIRST'))


class Group(NamedModel):
    AREA = 'area'
    WAY = 'way'
    KIND = (
        (WAY, 'way'),
        (AREA, 'area'),
    )
    CLASSICAL = 'classical'
    METRIC = 'metric'
    LINEAR = 'linear'
    MIXED = 'mixed'
    ANARCHICAL = 'anarchical'
    ADDRESSING = (
        (CLASSICAL, 'classical'),
        (METRIC, 'metric'),
        (LINEAR, 'linear'),
        (MIXED, 'mixed types'),
        (ANARCHICAL, 'anarchical'),
    )
    identifiers = ['fantoir', 'laposte', 'ign']
    resource_fields = ['name', 'alias', 'fantoir', 'municipality', 'kind',
                       'laposte', 'ign', 'addressing']

    kind = db.CharField(max_length=64, choices=KIND)
    addressing = db.CharField(max_length=16, choices=ADDRESSING, null=True)
    fantoir = db.FantoirField(null=True, unique=True)
    laposte = db.CharField(max_length=8, null=True, unique=True, format='\d*')
    ign = db.CharField(max_length=24, null=True, unique=True)
    municipality = db.CachedForeignKeyField(Municipality,
                                            related_name='groups')

    @property
    def housenumbers(self):
        qs = (self._housenumbers | self.housenumber_set)
        return qs.order_by(peewee.SQL('number ASC NULLS FIRST'),
                           peewee.SQL('ordinal ASC NULLS FIRST'))


class HouseNumber(Model):
    # INSEE + set of OCR-friendly characters (dropped confusing ones
    # (like 0/O, 1/I…)) from La Poste.
    CEA_FORMAT = Municipality.INSEE_FORMAT + '[234679ABCEGHILMNPRSTUVXYZ]{5}'
    identifiers = ['cia', 'laposte', 'ign']
    resource_fields = ['number', 'ordinal', 'parent', 'cia', 'laposte',
                       'ancestors', 'positions', 'ign', 'postcode']

    number = db.CharField(max_length=16, null=True)
    ordinal = db.CharField(max_length=16, null=True)
    parent = db.ForeignKeyField(Group)
    cia = db.CharField(max_length=100, null=True, unique=True)
    laposte = db.CharField(length=10, null=True, unique=True,
                           format=CEA_FORMAT)
    ign = db.CharField(max_length=24, null=True, unique=True)
    ancestors = db.ManyToManyField(Group, related_name='_housenumbers')
    postcode = db.CachedForeignKeyField(PostCode, null=True)

    class Meta:
        indexes = (
            (('parent', 'number', 'ordinal'), True),
        )

    def __str__(self):
        return ' '.join([self.number or '', self.ordinal or ''])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._clean_called = False

    @cached_property
    def municipality(self):
        return Municipality.select().join(
           Group, on=Municipality.pk == self.parent.municipality.pk).first()

    @property
    def as_export(self):
        """Resources plus relation references without metadata."""
        mask = {f: {} for f in self.resource_fields}
        return self.serialize(mask)


class Position(Model):

    POSTAL = 'postal'
    ENTRANCE = 'entrance'
    BUILDING = 'building'
    STAIRCASE = 'staircase'
    UNIT = 'unit'
    PARCEL = 'parcel'
    SEGMENT = 'segment'
    UTILITY = 'utility'
    UNKNOWN = 'unknown'
    AREA = 'area'
    KIND = (
        (POSTAL, _('postal delivery')),
        (ENTRANCE, _('entrance')),
        (BUILDING, _('building')),
        (STAIRCASE, _('staircase identifier')),
        (UNIT, _('unit identifier')),
        (PARCEL, _('parcel')),
        (SEGMENT, _('road segment')),
        (UTILITY, _('utility service')),
        (AREA, _('area')),
        (UNKNOWN, _('unknown')),
    )

    DGPS = 'dgps'
    GPS = 'gps'
    IMAGERY = 'imagery'
    PROJECTION = 'projection'
    INTERPOLATION = 'interpolation'
    OTHER = 'other'
    POSITIONING = (
        (DGPS, _('via differencial GPS')),
        (GPS, _('via GPS')),
        (IMAGERY, _('via imagery')),
        (PROJECTION, _('computed via projection')),
        (INTERPOLATION, _('computed via interpolation')),
        (OTHER, _('other')),
    )

    identifiers = ['laposte', 'ign']
    resource_fields = ['center', 'source', 'housenumber', 'kind', 'comment',
                       'parent', 'positioning', 'name', 'ign', 'laposte']

    name = db.CharField(max_length=200, null=True)
    center = db.PointField(verbose_name=_("center"), null=True, index=True)
    housenumber = db.ForeignKeyField(HouseNumber, related_name='positions')
    parent = db.ForeignKeyField('self', related_name='children', null=True)
    source = db.CharField(max_length=64, null=True)
    kind = db.CharField(max_length=64, choices=KIND)
    positioning = db.CharField(max_length=32, choices=POSITIONING)
    ign = db.CharField(max_length=24, null=True, unique=True)
    laposte = db.CharField(length=10, null=True, unique=True,
                           format=HouseNumber.CEA_FORMAT)
    comment = db.TextField(null=True)

    @classmethod
    def validate(cls, validator, document, instance):
        errors = {}
        default = instance and validator.update and instance.name
        name = document.get('name', default)
        default = instance and validator.update and instance.center
        center = document.get('center', default)
        if not name and not center:
            msg = 'A position must have either a center or a name.'
            errors['center'] = msg
            errors['name'] = msg
        return errors

    @cached_property
    def municipality(self):
        return Municipality.select().join(
               Group, on=Municipality.pk == Group.municipality).join(
               HouseNumber, on=Group.pk == self.housenumber.parent.pk).first()
