
#include <string.h>

#include <glib.h>

#include "gabble-presence-cache.h"

#include "gabble-presence.h"

G_DEFINE_TYPE (GabblePresence, gabble_presence, G_TYPE_OBJECT);

#define GABBLE_PRESENCE_PRIV(account) ((GabblePresencePrivate *)account->priv)

typedef struct _Resource Resource;

struct _Resource {
    gchar *name;
    GabblePresenceCapabilities caps;
    GabblePresenceId status;
    gchar *status_message;
    gint8 priority;
};

typedef struct _GabblePresencePrivate GabblePresencePrivate;

struct _GabblePresencePrivate {
    GSList *resources;
};

static Resource *
_resource_new (gchar *name)
{
  Resource *new = g_new (Resource, 1);
  new->name = name;
  new->caps = PRESENCE_CAP_NONE;
  new->status = GABBLE_PRESENCE_OFFLINE;
  new->status_message = NULL;
  new->priority = 0;
  return new;
}

static void
_resource_free (Resource *resource)
{
  g_free (resource->status_message);
  g_free (resource);
}

static void
gabble_presence_finalize (GObject *object)
{
  GSList *i;
  GabblePresence *presence = GABBLE_PRESENCE (object);
  GabblePresencePrivate *priv = GABBLE_PRESENCE_PRIV (presence);

  for (i = priv->resources; NULL != i; i = i->next)
    _resource_free (i->data);

  g_slist_free (priv->resources);
  g_free (presence->nickname);
}

static void
gabble_presence_class_init (GabblePresenceClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  g_type_class_add_private (object_class, sizeof (GabblePresencePrivate));
  object_class->finalize = gabble_presence_finalize;
}

static void
gabble_presence_init (GabblePresence *self)
{
  self->priv = G_TYPE_INSTANCE_GET_PRIVATE (self,
      GABBLE_TYPE_PRESENCE, GabblePresencePrivate);
  ((GabblePresencePrivate *)self->priv)->resources = NULL;
}

GabblePresence*
gabble_presence_new (void)
{
  return g_object_new (GABBLE_TYPE_PRESENCE, NULL);
}

const gchar *
gabble_presence_pick_resource_by_caps (
    GabblePresence *presence,
    GabblePresenceCapabilities caps)
{
  GabblePresencePrivate *priv = GABBLE_PRESENCE_PRIV (presence);
  GSList *i;
  Resource *chosen = NULL;

  for (i = priv->resources; NULL != i; i = i->next)
    {
      Resource *res = (Resource *) i->data;

      if ((res->priority >= 0) &&
          (res->caps & caps) &&
          (NULL == chosen || res->priority > chosen->priority))
        chosen = res;
    }

  if (chosen)
    return chosen->name;
  else
    return NULL;
}

void
gabble_presence_set_capabilities (GabblePresence *presence, const gchar *resource, GabblePresenceCapabilities caps)
{
  GabblePresencePrivate *priv = GABBLE_PRESENCE_PRIV (presence);
  GSList *i;

  for (i = priv->resources; NULL != i; i = i->next)
    {
      Resource *tmp = (Resource *) i->data;

      if (0 == strcmp (tmp->name, resource))
        {
          tmp->caps |= caps;
          presence->caps |= caps;
          break;
        }
    }
}

static Resource *
_find_resource (GabblePresence *presence, const gchar *resource)
{
  GSList *i;
  GabblePresencePrivate *priv = GABBLE_PRESENCE_PRIV (presence);

  for (i = priv->resources; NULL != i; i = i->next)
    {
      Resource *res = (Resource *) i->data;

      if (0 == strcmp (res->name, resource))
        return res;
    }

  return NULL;
}

gboolean
gabble_presence_update (GabblePresence *presence, const gchar *resource, GabblePresenceId status, const gchar *status_message, gint8 priority)
{
  GabblePresencePrivate *priv = GABBLE_PRESENCE_PRIV (presence);
  Resource *res;
  GabblePresenceId old_status;
  gchar *old_status_message;
  GSList *i;
  guint8 prio;

  g_assert (NULL != resource);

  res = _find_resource (presence, resource);

  if (GABBLE_PRESENCE_OFFLINE == status &&
      NULL == status_message)
    {
      if (NULL != res)
        {
          priv->resources = g_slist_remove (priv->resources, res);
          _resource_free (res);
          res = NULL;
        }
    }
  else
    {
      if (NULL == res)
        {
          res = _resource_new (g_strdup (resource));
          priv->resources = g_slist_append (priv->resources, res);
        }

      res->status = status;
      g_free (res->status_message);
      res->status_message = g_strdup (status_message);
      res->priority = priority;
    }

  old_status = presence->status;
  old_status_message = presence->status_message;
  presence->caps = 0;
  presence->status = GABBLE_PRESENCE_OFFLINE;
  presence->status_message = res ? res->status_message : NULL;
  prio = -128;

  for (i = priv->resources; NULL != i; i = i->next)
    {
      Resource *res = (Resource *) i->data;

      presence->caps |= res->caps;

      /* trump existing status & message if it's more present
       * or has the same presence and a higher priority */
      if (res->status > presence->status ||
          (res->status == presence->status && res->priority > prio))
        {
          presence->status = res->status;
          presence->status_message = res->status_message;
          prio = res->priority;
        }
    }

  if (presence->status != old_status)
    return TRUE;

  if (presence->status_message == old_status_message)
    return FALSE;

  if (NULL == presence->status_message && NULL != old_status_message)
    return TRUE;

  if (NULL == old_status_message && NULL != presence->status_message)
    return TRUE;

  if (0 != strcmp (presence->status_message, old_status_message))
    return TRUE;

  return FALSE;
}

LmMessage *
gabble_presence_as_message (GabblePresence *presence, const gchar *resource)
{
  LmMessage *message;
  LmMessageNode *node;
  LmMessageSubType subtype;
  Resource *res = _find_resource (presence, resource);

  g_assert (NULL != res);

  if (presence->status == GABBLE_PRESENCE_OFFLINE)
    subtype = LM_MESSAGE_SUB_TYPE_UNAVAILABLE;
  else
    subtype = LM_MESSAGE_SUB_TYPE_AVAILABLE;

  message = lm_message_new_with_sub_type (NULL, LM_MESSAGE_TYPE_PRESENCE,
              subtype);
  node = lm_message_get_node (message);

  switch (presence->status)
    {
    case GABBLE_PRESENCE_AVAILABLE:
    case GABBLE_PRESENCE_OFFLINE:
    case GABBLE_PRESENCE_HIDDEN:
      break;
    case GABBLE_PRESENCE_AWAY:
      lm_message_node_add_child (node, "show", JABBER_PRESENCE_SHOW_AWAY);
      break;
    case GABBLE_PRESENCE_CHAT:
      lm_message_node_add_child (node, "show", JABBER_PRESENCE_SHOW_CHAT);
      break;
    case GABBLE_PRESENCE_DND:
      lm_message_node_add_child (node, "show", JABBER_PRESENCE_SHOW_DND);
      break;
    case GABBLE_PRESENCE_XA:
      lm_message_node_add_child (node, "show", JABBER_PRESENCE_SHOW_XA);
      break;
    default:
      g_critical ("%s: Unexpected Telepathy presence type", G_STRFUNC);
      break;
    }

  if (presence->status_message)
      lm_message_node_add_child (node, "status", presence->status_message);

  if (res->priority)
    {
      gchar *priority = g_strdup_printf ("%d", res->priority);
      lm_message_node_add_child (node, "priority", priority);
      g_free (priority);
    }

  return message;
}

