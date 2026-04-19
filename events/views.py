from django.http import HttpResponse


def event_list(request):
    return HttpResponse("stub")


def event_detail(request, slug):
    return HttpResponse("stub")
