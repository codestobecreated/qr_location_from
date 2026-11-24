from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

PAGE_SIZES = (25, 50, 100)


def paginate(request, queryset, default=25):
    try:
        per_page = int(request.GET.get("per_page", default))
    except ValueError:
        per_page = default
    if per_page not in PAGE_SIZES:
        per_page = default
    paginator = Paginator(queryset, per_page)
    try:
        page = paginator.page(request.GET.get("page", 1))
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    return page
