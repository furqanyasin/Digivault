from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """Wraps every API response in {data, errors, meta} envelope.

    Views that need to customise meta can set `response.meta` on the
    Response object before returning it.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get("response") if renderer_context else None
        meta = getattr(response, "meta", {})

        # Already wrapped by the exception handler — pass through
        if isinstance(data, dict) and "errors" in data and "data" in data:
            return super().render(data, accepted_media_type, renderer_context)

        envelope = {
            "data": data,
            "errors": [],
            "meta": meta,
        }
        return super().render(envelope, accepted_media_type, renderer_context)
