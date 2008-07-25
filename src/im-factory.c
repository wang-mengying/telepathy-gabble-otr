/*
 * im-factory.c - Source for GabbleImFactory
 * Copyright (C) 2006 Collabora Ltd.
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 */

#include "config.h"
#include "im-factory.h"

#define DBUS_API_SUBJECT_TO_CHANGE

#include <string.h>

#include <dbus/dbus-glib.h>
#include <dbus/dbus-glib-lowlevel.h>
#include <loudmouth/loudmouth.h>
#include <telepathy-glib/interfaces.h>
#include <telepathy-glib/channel-factory-iface.h>

#define DEBUG_FLAG GABBLE_DEBUG_IM

#include "channel-manager.h"
#include "connection.h"
#include "debug.h"
#include "disco.h"
#include "im-channel.h"
#include "text-mixin.h"

static void gabble_im_factory_iface_init (gpointer g_iface,
    gpointer iface_data);

G_DEFINE_TYPE_WITH_CODE (GabbleImFactory, gabble_im_factory, G_TYPE_OBJECT,
    G_IMPLEMENT_INTERFACE (GABBLE_TYPE_CHANNEL_MANAGER, NULL);
    G_IMPLEMENT_INTERFACE (TP_TYPE_CHANNEL_FACTORY_IFACE,
      gabble_im_factory_iface_init));

/* properties */
enum
{
  PROP_CONNECTION = 1,
  LAST_PROPERTY
};

struct _GabbleImFactoryPrivate
{
  GabbleConnection *conn;
  LmMessageHandler *message_cb;
  GHashTable *channels;

  gboolean dispose_has_run;
};

#define GABBLE_IM_FACTORY_GET_PRIVATE(o) \
  (G_TYPE_INSTANCE_GET_PRIVATE ((o), GABBLE_TYPE_IM_FACTORY,\
                                GabbleImFactoryPrivate))


static void
gabble_im_factory_init (GabbleImFactory *self)
{
  self->priv = G_TYPE_INSTANCE_GET_PRIVATE (self, GABBLE_TYPE_IM_FACTORY,
      GabbleImFactoryPrivate);

  self->priv->channels = g_hash_table_new_full (g_direct_hash, g_direct_equal,
                                          NULL, g_object_unref);

  self->priv->message_cb = NULL;

  self->priv->conn = NULL;
  self->priv->dispose_has_run = FALSE;
}

static GObject *
gabble_im_factory_constructor (GType type, guint n_props,
                               GObjectConstructParam *props)
{
  GObject *obj;
  /* GabbleImFactoryPrivate *priv; */

  obj = G_OBJECT_CLASS (gabble_im_factory_parent_class)->
           constructor (type, n_props, props);
  /* priv = GABBLE_IM_FACTORY_GET_PRIVATE (obj); */

  return obj;
}


static void
gabble_im_factory_dispose (GObject *object)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (object);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);

  if (priv->dispose_has_run)
    return;

  DEBUG ("dispose called");
  priv->dispose_has_run = TRUE;

  tp_channel_factory_iface_close_all (TP_CHANNEL_FACTORY_IFACE (object));
  g_assert (priv->channels == NULL);

  if (G_OBJECT_CLASS (gabble_im_factory_parent_class)->dispose)
    G_OBJECT_CLASS (gabble_im_factory_parent_class)->dispose (object);
}

static void
gabble_im_factory_get_property (GObject    *object,
                                 guint       property_id,
                                 GValue     *value,
                                 GParamSpec *pspec)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (object);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);

  switch (property_id) {
    case PROP_CONNECTION:
      g_value_set_object (value, priv->conn);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, property_id, pspec);
      break;
  }
}

static void
gabble_im_factory_set_property (GObject      *object,
                                 guint         property_id,
                                 const GValue *value,
                                 GParamSpec   *pspec)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (object);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);

  switch (property_id) {
    case PROP_CONNECTION:
      priv->conn = g_value_get_object (value);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, property_id, pspec);
      break;
  }
}

static void
gabble_im_factory_class_init (GabbleImFactoryClass *gabble_im_factory_class)
{
  GObjectClass *object_class = G_OBJECT_CLASS (gabble_im_factory_class);
  GParamSpec *param_spec;

  g_type_class_add_private (gabble_im_factory_class,
      sizeof (GabbleImFactoryPrivate));

  object_class->constructor = gabble_im_factory_constructor;
  object_class->dispose = gabble_im_factory_dispose;

  object_class->get_property = gabble_im_factory_get_property;
  object_class->set_property = gabble_im_factory_set_property;

  param_spec = g_param_spec_object ("connection", "GabbleConnection object",
                                    "Gabble connection object that owns this "
                                    "IM channel factory object.",
                                    GABBLE_TYPE_CONNECTION,
                                    G_PARAM_CONSTRUCT_ONLY |
                                    G_PARAM_READWRITE |
                                    G_PARAM_STATIC_NICK |
                                    G_PARAM_STATIC_BLURB);
  g_object_class_install_property (object_class, PROP_CONNECTION, param_spec);

}

static GabbleIMChannel *new_im_channel (GabbleImFactory *fac,
    TpHandle handle, TpHandle initiator);

static void im_channel_closed_cb (GabbleIMChannel *chan, gpointer user_data);


/**
 * im_factory_message_cb:
 *
 * Called by loudmouth when we get an incoming <message>.
 */
static LmHandlerResult
im_factory_message_cb (LmMessageHandler *handler,
                       LmConnection *lmconn,
                       LmMessage *message,
                       gpointer user_data)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (user_data);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);
  TpBaseConnection *conn = (TpBaseConnection *) priv->conn;
  TpHandleRepoIface *contact_repo = tp_base_connection_get_handles (conn,
      TP_HANDLE_TYPE_CONTACT);
  const gchar *from, *body;
  time_t stamp;
  TpChannelTextMessageType msgtype;
  TpHandle handle;
  GabbleIMChannel *chan;
  gint state;
  TpChannelTextSendError send_error;

  if (!gabble_text_mixin_parse_incoming_message (message, &from, &stamp,
        &msgtype, &body, &state, &send_error))
    return LM_HANDLER_RESULT_REMOVE_MESSAGE;

  if (body == NULL && state == -1)
    {
      return LM_HANDLER_RESULT_ALLOW_MORE_HANDLERS;
    }

  handle = tp_handle_ensure (contact_repo, from, NULL, NULL);
  if (handle == 0)
    {
      NODE_DEBUG (message->node, "ignoring message node from malformed jid");
      return LM_HANDLER_RESULT_REMOVE_MESSAGE;
    }

  chan = g_hash_table_lookup (priv->channels, GINT_TO_POINTER (handle));

  if (chan == NULL)
    {
      if (send_error != GABBLE_TEXT_CHANNEL_SEND_NO_ERROR)
        {
          DEBUG ("ignoring message error; no sending channel");
          tp_handle_unref (contact_repo, handle);
          return LM_HANDLER_RESULT_REMOVE_MESSAGE;
        }

      if (body == NULL)
        {
          /* don't create a new channel if all we have is a chat state */
          DEBUG ("ignoring message without body; no existing channel");
          tp_handle_unref (contact_repo, handle);
          return LM_HANDLER_RESULT_REMOVE_MESSAGE;
        }

      DEBUG ("found no IM channel, creating one");

      chan = new_im_channel (fac, handle, handle);
    }

  g_assert (chan != NULL);

  /* now the channel is referencing the handle, so if we unref it, that's
   * not a problem */
  tp_handle_unref (contact_repo, handle);

  if (send_error != GABBLE_TEXT_CHANNEL_SEND_NO_ERROR)
    {
      if (body == NULL)
        {
          DEBUG ("ignoring error sending chat state to %s (handle %u)", from,
              handle);
          return LM_HANDLER_RESULT_REMOVE_MESSAGE;
        }

      DEBUG ("got error sending to %s (handle %u), msgtype %u, body:\n%s",
         from, handle, msgtype, body);

      tp_svc_channel_type_text_emit_send_error ((TpSvcChannelTypeText *) chan,
          send_error, stamp, msgtype, body);

      return LM_HANDLER_RESULT_REMOVE_MESSAGE;
    }

  if (state != -1)
    _gabble_im_channel_state_receive (chan, state);

  if (body != NULL)
    _gabble_im_channel_receive (chan, msgtype, handle, from, stamp, body);

  return LM_HANDLER_RESULT_REMOVE_MESSAGE;
}

/**
 * im_channel_closed_cb:
 *
 * Signal callback for when an IM channel is closed. Removes the references
 * that #GabbleConnection holds to them - unless the channel has pending
 * messages, in which case it is re-announced (so from the perspective of the
 * D-Bus API, it was replaced by an identical channel).
 */
static void
im_channel_closed_cb (GabbleIMChannel *chan, gpointer user_data)
{
  GabbleImFactory *self = GABBLE_IM_FACTORY (user_data);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (self);
  TpHandle contact_handle;
  gboolean really_destroyed;
  gchar *object_path;

  DEBUG ("%p, channel %p", self, chan);

  g_object_get (chan,
      "handle", &contact_handle,
      "object-path", &object_path,
      "channel-destroyed", &really_destroyed,
      NULL);

  g_signal_emit_by_name (self, "channel-closed", object_path);

  if (priv->channels != NULL)
    {
      g_object_get (chan,
          "handle", &contact_handle,
          "channel-destroyed", &really_destroyed,
          NULL);

      if (really_destroyed)
        {
          DEBUG ("removing channel with handle %u", contact_handle);
          g_hash_table_remove (priv->channels,
              GUINT_TO_POINTER (contact_handle));
        }
      else
        {
          GPtrArray *array = g_ptr_array_sized_new (1);

          DEBUG ("reopening channel with handle %u due to pending messages",
              contact_handle);
          tp_channel_factory_iface_emit_new_channel (self,
              (TpChannelIface *) chan, NULL);
          g_ptr_array_add (array, chan);
          g_signal_emit_by_name (self, "new-channels", array);
          g_ptr_array_free (array, TRUE);
        }
    }

  g_free (object_path);
}

/**
 * new_im_channel
 */
static GabbleIMChannel *
new_im_channel (GabbleImFactory *fac,
                TpHandle handle,
                TpHandle initiator)
{
  GabbleImFactoryPrivate *priv;
  TpBaseConnection *conn;
  GabbleIMChannel *chan;
  char *object_path;
  GPtrArray *channels;

  g_return_val_if_fail (GABBLE_IS_IM_FACTORY (fac), NULL);
  g_return_val_if_fail (handle != 0, NULL);
  g_return_val_if_fail (initiator != 0, NULL);

  priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);
  conn = (TpBaseConnection *) priv->conn;

  object_path = g_strdup_printf ("%s/ImChannel%u",
      conn->object_path, handle);

  chan = g_object_new (GABBLE_TYPE_IM_CHANNEL,
                       "connection", priv->conn,
                       "object-path", object_path,
                       "handle", handle,
                       "initiator-handle", initiator,
                       NULL);

  DEBUG ("object path %s", object_path);

  g_signal_connect (chan, "closed", (GCallback) im_channel_closed_cb, fac);

  g_hash_table_insert (priv->channels, GINT_TO_POINTER (handle), chan);

  tp_channel_factory_iface_emit_new_channel (fac, (TpChannelIface *) chan,
      NULL);

  g_free (object_path);

  channels = g_ptr_array_sized_new (1);
  g_ptr_array_add (channels, chan);
  g_signal_emit_by_name (self, "new-channels", channels);
  g_ptr_array_free (channels, TRUE);

  return chan;
}

static void
gabble_im_factory_iface_close_all (TpChannelFactoryIface *iface)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (iface);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);

  DEBUG ("closing channels");

  if (priv->channels)
    {
      GHashTable *tmp = priv->channels;
      priv->channels = NULL;
      g_hash_table_destroy (tmp);
    }
}

static void
gabble_im_factory_iface_connecting (TpChannelFactoryIface *iface)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (iface);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);

  DEBUG ("adding callbacks");

  g_assert (priv->message_cb == NULL);

  priv->message_cb = lm_message_handler_new (im_factory_message_cb, fac, NULL);
  lm_connection_register_message_handler (priv->conn->lmconn, priv->message_cb,
                                          LM_MESSAGE_TYPE_MESSAGE,
                                          LM_HANDLER_PRIORITY_LAST);
}



static void
gabble_im_factory_iface_connected (TpChannelFactoryIface *iface)
{
  /* nothing to do */
}

static void
gabble_im_factory_iface_disconnected (TpChannelFactoryIface *iface)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (iface);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);

  DEBUG ("removing callbacks");

  g_assert (priv->message_cb != NULL);

  lm_connection_unregister_message_handler (priv->conn->lmconn,
      priv->message_cb, LM_MESSAGE_TYPE_MESSAGE);
  lm_message_handler_unref (priv->message_cb);
  priv->message_cb = NULL;
}

struct _ForeachData
{
  TpChannelFunc foreach;
  gpointer user_data;
};

static void
_foreach_slave (gpointer key, gpointer value, gpointer user_data)
{
  struct _ForeachData *data = (struct _ForeachData *) user_data;
  TpChannelIface *chan = TP_CHANNEL_IFACE (value);

  data->foreach (chan, data->user_data);
}

static void
gabble_im_factory_iface_foreach (TpChannelFactoryIface *iface,
                                 TpChannelFunc foreach,
                                 gpointer user_data)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (iface);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);
  struct _ForeachData data;

  data.user_data = user_data;
  data.foreach = foreach;

  g_hash_table_foreach (priv->channels, _foreach_slave, &data);
}

static TpChannelFactoryRequestStatus
gabble_im_factory_iface_request (TpChannelFactoryIface *iface,
                                 const gchar *chan_type,
                                 TpHandleType handle_type,
                                 guint handle,
                                 gpointer request,
                                 TpChannelIface **ret,
                                 GError **error)
{
  GabbleImFactory *fac = GABBLE_IM_FACTORY (iface);
  GabbleImFactoryPrivate *priv = GABBLE_IM_FACTORY_GET_PRIVATE (fac);
  TpBaseConnection *base_conn = (TpBaseConnection *) priv->conn;
  TpHandleRepoIface *contact_repo = tp_base_connection_get_handles (
      base_conn, TP_HANDLE_TYPE_CONTACT);
  GabbleIMChannel *chan;
  TpChannelFactoryRequestStatus status;

  if (strcmp (chan_type, TP_IFACE_CHANNEL_TYPE_TEXT))
    return TP_CHANNEL_FACTORY_REQUEST_STATUS_NOT_IMPLEMENTED;

  if (handle_type != TP_HANDLE_TYPE_CONTACT)
    return TP_CHANNEL_FACTORY_REQUEST_STATUS_NOT_AVAILABLE;

  if (!tp_handle_is_valid (contact_repo, handle, error))
    return TP_CHANNEL_FACTORY_REQUEST_STATUS_ERROR;

  chan = g_hash_table_lookup (priv->channels, GINT_TO_POINTER (handle));

  status = TP_CHANNEL_FACTORY_REQUEST_STATUS_EXISTING;
  if (!chan)
    {
      status = TP_CHANNEL_FACTORY_REQUEST_STATUS_CREATED;
      chan = new_im_channel (fac, handle, base_conn->self_handle);
    }

  g_assert (chan);
  *ret = TP_CHANNEL_IFACE (chan);
  return status;
}

static void
gabble_im_factory_iface_init (gpointer g_iface,
                              gpointer iface_data)
{
  TpChannelFactoryIfaceClass *klass = (TpChannelFactoryIfaceClass *) g_iface;

  klass->close_all = gabble_im_factory_iface_close_all;
  klass->connecting = gabble_im_factory_iface_connecting;
  klass->connected = gabble_im_factory_iface_connected;
  klass->disconnected = gabble_im_factory_iface_disconnected;
  klass->foreach = gabble_im_factory_iface_foreach;
  klass->request = gabble_im_factory_iface_request;
}

