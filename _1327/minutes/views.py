from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.forms import inlineformset_factory
from django.forms.formsets import formset_factory
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _
from guardian.models import Group
from guardian.shortcuts import get_objects_for_user, get_perms

import markdown
from markdown.extensions.toc import TocExtension

from _1327 import settings
from _1327.documents.forms import PermissionForm
from _1327.documents.markdown_internal_links import InternalLinksMarkdownExtension
from _1327.documents.models import Document
from _1327.documents.utils import (
	delete_old_empty_pages,
	handle_attachment,
	handle_autosave,
	handle_edit,
	permission_warning,
	prepare_versions,
)
from _1327.information_pages.models import InformationDocument
from _1327.polls.models import Poll
from _1327.user_management.shortcuts import get_object_or_error
from .forms import GuestForm
from .models import Guest, MinutesDocument


@login_required
def list(request):
	years = {}
	minutes = MinutesDocument.objects.order_by('-date')
	for m in minutes:
		if not request.user.has_perm(m, MinutesDocument.get_view_permission()):
			continue

		if m.date.year not in years:
			years[m.date.year] = []
		years[m.date.year].append(m)
	new_years = [{'year': year, 'minutes': minutes} for (year, minutes) in years.items()]
	new_years = sorted(new_years, key=lambda x: x['year'], reverse=True)
	return render(request, "minutes_list.html", {
		'years': new_years,
	})


def create(request):
	if request.user.has_perm("information_pages.add_informationdocument"):
		delete_old_empty_pages()
		title = _("New minutes document from {}").format(str(datetime.now()))
		url_title = slugify(title)
		MinutesDocument.objects.get_or_create(author=request.user, url_title=url_title, title=title, moderator=request.user)
		return edit(request, url_title)
	else:
		return HttpResponseForbidden()


def edit(request, title):
	document = get_object_or_error(MinutesDocument, request.user, ['minutes.change_minutesdocument'], url_title=title)

	guestFormset = inlineformset_factory(MinutesDocument, Guest, form=GuestForm, can_delete=True, extra=1)
	formset = guestFormset(request.POST or None, instance=document)

	success, form = handle_edit(request, document, formset)
	__, attachment_form, __ = handle_attachment(request, document)
	if success:
		messages.success(request, _("Successfully saved changes"))
		return HttpResponseRedirect(reverse('minutes:view', args=[document.url_title]))
	else:

		minutes = get_objects_for_user(request.user, MinutesDocument.VIEW_PERMISSION_NAME, klass=MinutesDocument)
		information_documents = get_objects_for_user(request.user, InformationDocument.VIEW_PERMISSION_NAME, klass=InformationDocument)
		polls = get_objects_for_user(request.user, Poll.VIEW_PERMISSION_NAME, klass=Poll)

		return render(request, "minutes_edit.html", {
			'document': document,
			'edit_url': reverse('minutes:edit', args=[document.url_title]),
			'form': form,
			'attachment_form': attachment_form,
			'active_page': 'edit',
			'guest_formset': formset,
			'permission_warning': permission_warning(request.user, document),
			'supported_image_types': settings.SUPPORTED_IMAGE_TYPES,
			'minutes': minutes,
			'information_documents': information_documents,
			'polls': polls,
		})


def autosave(request, title):
	document = None
	try:
		document = get_object_or_error(MinutesDocument, request.user, ['minutes.change_minutesdocument'], url_title=title)
	except Document.DoesNotExist:
		pass

	handle_autosave(request, document)
	return HttpResponse()


def versions(request, title):
	# get all versions of the document
	document = get_object_or_error(MinutesDocument, request.user, ['minutes.change_minutesdocument'], url_title=title)
	document_versions = prepare_versions(document)

	return render(request, 'minutes_versions.html', {
		'active_page': 'versions',
		'versions': document_versions,
		'document': document,
		'permission_warning': permission_warning(request.user, document),
	})


def view(request, title):
	document = get_object_or_error(MinutesDocument, request.user, [MinutesDocument.get_view_permission()], url_title=title)

	md = markdown.Markdown(safe_mode='escape', extensions=[TocExtension(baselevel=2), InternalLinksMarkdownExtension()])
	text = md.convert(document.text)

	return render(request, 'minutes_base.html', {
		'document': document,
		'text': text,
		'toc': md.toc,
		'attachments': document.attachments.filter(no_direct_download=False).order_by('index'),
		'active_page': 'view',
		'permission_warning': permission_warning(request.user, document),
	})


def permissions(request, title):
	document = get_object_or_error(MinutesDocument, request.user, ['minutes.change_minutesdocument'], url_title=title)

	permissionFS = formset_factory(form=PermissionForm, extra=0)
	groups = Group.objects.all()

	initial_data = []
	for group in groups:
		group_permissions = get_perms(group, document)
		data = {
			"change_permission": "change_minutesdocument" in group_permissions,
			"delete_permission": "delete_minutesdocument" in group_permissions,
			"view_permission": MinutesDocument.VIEW_PERMISSION_NAME in group_permissions,
			"group_name": group.name,
		}
		initial_data.append(data)

	formset = permissionFS(request.POST or None, initial=initial_data)
	if request.POST and formset.is_valid():
		for form in formset:
			form.save(document)
		messages.success(request, _("Permissions have been changed successfully."))

		return HttpResponseRedirect(reverse('minutes:permissions', args=[document.url_title]))

	return render(request, 'minutes_permissions.html', {
		'document': document,
		'formset': formset,
		'active_page': 'permissions',
		'permission_warning': permission_warning(request.user, document),
	})


def attachments(request, title):
	document = get_object_or_error(MinutesDocument, request.user, ['minutes.change_minutesdocument'], url_title=title)

	success, form, __ = handle_attachment(request, document)
	if success:
		messages.success(request, _("File has been uploaded successfully!"))
		return HttpResponseRedirect(reverse("minutes:attachments", args=[document.url_title]))
	else:
		return render(request, "minutes_attachments.html", {
			'document': document,
			'edit_url': reverse('minutes:attachments', args=[document.url_title]),
			'form': form,
			'attachments': document.attachments.all().order_by('index'),
			'active_page': 'attachments',
			'permission_warning': permission_warning(request.user, document),
		})
