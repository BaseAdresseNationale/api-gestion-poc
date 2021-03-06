import yaml

from ban import __version__, db


BASE = {
    'info': {
        'title': 'Api de gestion de la Base adresse nationale',
        'contact': {
            'name': 'Equipe support',
            'email': 'contact@ban.somewhere.fr',
        },
        'license': {
            'name': 'XXXX',
            'url': 'http://xxxx.org',
        },
        'version': __version__,
    },
    'swagger': '2.0',
    'schemes': ['https'],
    'consumes': ['application/json'],
    'produces': ['application/json'],
    'externalDocs': {
        'url': 'https://adresse.data.gouv.fr/api-gestion/',
    },
    'paths': {},
    'definitions': {
        'Error': {
            'properties': {
                'title': {
                    'type': 'string',
                    'description': 'Summary of the error'
                },
                'description': {
                    'type': 'string',
                    'description': 'Description of the error'
                },
            }
        }
    },
    'parameters': {
        'identifier': {
            'name': 'identifier',
            'in': 'path',
            'type': 'string',
            'required': True,
            'description': 'resource identifier'
        }
    },
    'responses': {
        '400': {
            'description': 'Bad Request.',
            'schema': {
                'type': 'object',
                '$ref': '#/definitions/Error'
            }
        },
        '401': {
            'description': 'Unauthorized access.',
            'schema': {
                'type': 'object',
                '$ref': '#/definitions/Error'
            }
        },
        '404': {
            'description': 'Resource does not exist.',
            'schema': {
                'type': 'object',
                '$ref': '#/definitions/Error'
            }
        },
        '410': {
            'description': 'Resource is deleted.',
            'schema': {
                'type': 'object',
                '$ref': '#/definitions/Error'
            }
        },
        '422': {
            'description': 'Invalid data.',
            'schema': {
                'type': 'object',
                '$ref': '#/definitions/Error'
            }
        },
    }
}


class Schema(dict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update(BASE)

    def get_responder_summary(self, responder, resource):
        return (responder.__doc__ or '').split('\n\n')[0].format(
            resource=resource.__name__)

    def get_responder_doc(self, func, resource):
        default = {
            'summary': self.get_responder_summary(func, resource),
        }
        try:
            doc = (func.__doc__ or '').split('\n\n')[1]
        except IndexError:
            print('Bad openapi docstring for {}'.format(func))
        else:
            try:
                extra = yaml.load(doc.format(resource=resource.__name__))
            except:
                print('Bad openapi docstring for {}'.format(func))
            else:
                default.update(extra)
        return default

    def register_model(self, model):
        if hasattr(model, '__openapi__'):
            definition = yaml.load(model.__openapi__)
        else:
            definition = self.model_definition(model)
        self['definitions'][model.__name__] = definition

    def model_definition(self, model):
        """Map Peewee models to jsonschema."""
        schema = {'required': [], 'properties': {},
                  'type': ['object', 'string', 'null']}
        for name, field in model._meta.fields.items():
            if name not in model.resource_fields:
                continue
            if field.primary_key:
                continue
            type_ = getattr(field.__class__, '__schema_type__', None)
            if not type_:
                continue
            row = {
                'type': [type_]
            }
            if hasattr(field.__class__, '__schema_format__'):
                row['format'] = field.__class__.__schema_format__
            if isinstance(field, db.ForeignKeyField):
                row['type'] = ['object', 'string']
                row['$ref'] = '#/definitions/{}'.format(
                    field.rel_model.__name__)
            if isinstance(field, db.ManyToManyField):
                row['items'] = {
                    '$ref': '#/definitions/{}'.format(
                        field.rel_model.__name__)
                }
            elif type_ == 'array':
                row['items'] = {'type': field.db_field}
            if field.null and 'type' in row:
                row['type'].append('null')
            if field.unique:
                row['unique'] = True
            max_length = getattr(field, 'max_length', None)
            if max_length:
                row['maxLength'] = max_length
            min_length = getattr(field, 'min_length', None)
            if not min_length and type_ == 'string' and not field.null:
                min_length = 1
            if min_length:
                row['minLength'] = min_length
            if getattr(field, 'choices', None):
                row['enum'] = [v for v, l in field.choices]
                if field.null:
                    row['enum'].append(None)
            schema['properties'][name] = row
            readonly = name in model.readonly_fields
            if (not field.null and not readonly
               and name not in schema['required']):
                schema['required'].append(name)
        return schema

    def register_endpoint(self, path, func, methods, endpoint):
        definition = {verb.lower(): self.get_responder_doc(func, endpoint)
                      for verb in methods}
        if path in self['paths']:
            self['paths'][path].update(definition)
        else:
            self['paths'][path] = definition
