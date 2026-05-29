from django.contrib import admin

from syndication.models import ContentVersion

# Trivial registration — no list_display or field references that could
# break test collection (kb-wz8m.1 constraint: additive-only, no breakage).
admin.site.register(ContentVersion)
