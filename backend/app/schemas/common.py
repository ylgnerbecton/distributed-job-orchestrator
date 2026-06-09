from marshmallow import Schema, fields


class HealthSchema(Schema):
    status = fields.Str()
    database = fields.Str()
    queue = fields.Str()


class MessageSchema(Schema):
    message = fields.Str()
