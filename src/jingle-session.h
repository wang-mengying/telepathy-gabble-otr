/*
 * jingle-session.h - Header for GabbleJingleSession
 * Copyright (C) 2008 Collabora Ltd.
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

#ifndef __JINGLE_SESSION_H__
#define __JINGLE_SESSION_H__

#include <glib-object.h>
#include <loudmouth/loudmouth.h>
#include "types.h"
#include "jingle-factory.h"

#include "jingle-content.h"

G_BEGIN_DECLS

typedef enum
{
  MODE_GOOGLE,
  MODE_JINGLE
} GabbleMediaSessionMode;

typedef enum {
    JS_STATE_INVALID = -1,
    JS_STATE_PENDING_CREATED = 0,
    JS_STATE_PENDING_INITIATE_SENT,
    JS_STATE_PENDING_INITIATED,
    JS_STATE_PENDING_ACCEPT_SENT,
    JS_STATE_ACTIVE,
    JS_STATE_ENDED
} JingleSessionState;

typedef struct _GabbleJingleSessionClass GabbleJingleSessionClass;

GType gabble_jingle_session_get_type (void);

/* TYPE MACROS */
#define GABBLE_TYPE_JINGLE_SESSION \
  (gabble_jingle_session_get_type ())
#define GABBLE_JINGLE_SESSION(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST((obj), GABBLE_TYPE_JINGLE_SESSION, \
                              GabbleJingleSession))
#define GABBLE_JINGLE_SESSION_CLASS(klass) \
  (G_TYPE_CHECK_CLASS_CAST((klass), GABBLE_TYPE_JINGLE_SESSION, \
                           GabbleJingleSessionClass))
#define GABBLE_IS_JINGLE_SESSION(obj) \
  (G_TYPE_CHECK_INSTANCE_TYPE((obj), GABBLE_TYPE_JINGLE_SESSION))
#define GABBLE_IS_JINGLE_SESSION_CLASS(klass) \
  (G_TYPE_CHECK_CLASS_TYPE((klass), GABBLE_TYPE_JINGLE_SESSION))
#define GABBLE_JINGLE_SESSION_GET_CLASS(obj) \
  (G_TYPE_INSTANCE_GET_CLASS ((obj), GABBLE_TYPE_JINGLE_SESSION, \
                              GabbleJingleSessionClass))

struct _GabbleJingleSessionClass {
    GObjectClass parent_class;
};

struct _GabbleJingleSession {
    GObject parent;
    gpointer priv;

    TpHandle peer;
};

const gchar *gabble_jingle_session_parse (GabbleJingleSession *sess,
    LmMessage *message, GError **error);
LmMessage *gabble_jingle_session_new_message (GabbleJingleSession *sess,
    JingleAction action, LmMessageNode **sess_node);

const gchar *_enum_to_string (const gchar **table, gint val);
gint _string_to_enum (const gchar **table, const gchar *val);

void gabble_jingle_session_accept (GabbleJingleSession *sess);
void gabble_jingle_session_terminate (GabbleJingleSession *sess);
void gabble_jingle_session_remove_content (GabbleJingleSession *sess,
    GabbleJingleContent *c);

GabbleJingleContent *
gabble_jingle_session_add_content (GabbleJingleSession *sess, JingleMediaType mtype,
    const gchar *content_ns, const gchar *transport_ns);

GType gabble_jingle_session_get_content_type (GabbleJingleSession *);
GList *gabble_jingle_session_get_contents (GabbleJingleSession *sess);

typedef void (*JingleReplyHandler) (GabbleJingleSession *, gboolean success,
    LmMessage *reply, gpointer user_data);
void gabble_jingle_session_send (GabbleJingleSession *sess, LmMessage *msg,
    JingleReplyHandler cb, gpointer user_data);


#endif /* __JINGLE_SESSION_H__ */
