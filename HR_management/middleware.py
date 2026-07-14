class NoCacheForAuthenticatedMiddleware:
    """Stop the browser caching logged-in / staff pages.

    Without this the browser's back button can show a protected page after
    logout, and edits can appear "not saved" because a stale cached page is
    shown. We send no-store on authenticated requests and the HR/admin areas.
    """
    PROTECTED_PREFIXES = ('/hr/', '/admin/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        is_protected = (getattr(request, 'user', None) and request.user.is_authenticated) \
            or request.path.startswith(self.PROTECTED_PREFIXES)
        if is_protected:
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        return response
