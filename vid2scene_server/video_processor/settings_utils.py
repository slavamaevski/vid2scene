# Workaround to allow sorl.thumbnail to use a different storage backend in Django 5.1.
# See https://github.com/jazzband/sorl-thumbnail/issues/748
def alias_thumbnail_storage(*args):
    from django.core.files.storage import storages

    return storages["thumbnails"]
