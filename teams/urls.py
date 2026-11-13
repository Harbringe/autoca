from django.urls import path

from teams import views

urlpatterns = [
    path("members/", views.MembersView.as_view(), name="team-members"),
    path("members/bulk/", views.MembersBulkView.as_view(), name="team-members-bulk"),
    path("members/<uuid:pk>/", views.MemberView.as_view(), name="team-member"),
    path("members/<uuid:pk>/work/", views.MemberWorkView.as_view(), name="team-member-work"),
    path("clients/", views.ClientsView.as_view(), name="team-clients"),
    path("clients/<uuid:pk>/lead/", views.ClientLeadView.as_view(), name="team-client-lead"),
    path("clients/<uuid:pk>/team/", views.ClientTeamView.as_view(), name="team-client-team"),
    path(
        "clients/<uuid:pk>/team/<uuid:member_id>/",
        views.ClientTeamView.as_view(),
        name="team-client-team-member",
    ),
    path("invites/", views.InvitesView.as_view(), name="team-invites"),
    path("invites/<uuid:pk>/", views.InviteView.as_view(), name="team-invite"),
    path("invites/<uuid:pk>/regenerate/", views.InviteRegenerateView.as_view(), name="team-invite-regenerate"),
    path("invites/<uuid:pk>/extend/", views.InviteExtendView.as_view(), name="team-invite-extend"),
    path("events/", views.EventsView.as_view(), name="team-events"),
]
