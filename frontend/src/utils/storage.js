// Abstract storage adapter for conversation persistence
// Can be easily swapped with Supabase, IndexedDB, Firebase, PostgreSQL, etc.

const LOCAL_STORAGE_KEY = 'd2c_chat_sessions';

export const ChatStorage = {
  // Helper: Load conversations from LocalStorage (Guest Mode)
  getLocalConversations() {
    try {
      const data = localStorage.getItem(LOCAL_STORAGE_KEY);
      return data ? JSON.parse(data) : [];
    } catch (e) {
      console.error('Error reading localStorage', e);
      return [];
    }
  },

  // Helper: Save conversations to LocalStorage (Guest Mode)
  saveLocalConversations(convs) {
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(convs));
    } catch (e) {
      console.error('Error writing to localStorage', e);
    }
  },

  // GET: Fetch all conversations
  async getConversations(userId) {
    if (!userId) {
      // Guest Mode: load from local storage
      return this.getLocalConversations();
    }

    try {
      const response = await fetch(`http://localhost:8000/api/conversations?user_id=${userId}`);
      if (!response.ok) throw new Error('Failed to fetch from backend');
      return await response.json();
    } catch (e) {
      console.error('Fetch error, falling back to LocalStorage', e);
      return this.getLocalConversations();
    }
  },

  // POST: Create or update a conversation
  async saveConversation(userId, conversation) {
    if (!userId) {
      // Guest Mode: save locally
      const local = this.getLocalConversations();
      const idx = local.findIndex(c => c.conversation_id === conversation.conversation_id);
      
      const updatedConv = {
        ...conversation,
        updated_at: new Date().toISOString()
      };

      if (idx > -1) {
        local[idx] = updatedConv;
      } else {
        local.push(updatedConv);
      }
      this.saveLocalConversations(local);
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conversation)
      });
      if (!response.ok) throw new Error('Failed to save to database');
    } catch (e) {
      console.error('Database save error, backing up to LocalStorage', e);
      // Fallback backup
      const local = this.getLocalConversations();
      const idx = local.findIndex(c => c.conversation_id === conversation.conversation_id);
      if (idx > -1) local[idx] = conversation;
      else local.push(conversation);
      this.saveLocalConversations(local);
    }
  },

  // PUT: Rename a conversation
  async renameConversation(userId, conversationId, title) {
    if (!userId) {
      // Guest Mode: rename locally
      const local = this.getLocalConversations();
      const idx = local.findIndex(c => c.conversation_id === conversationId);
      if (idx > -1) {
        local[idx].title = title;
        local[idx].updated_at = new Date().toISOString();
        this.saveLocalConversations(local);
      }
      return;
    }

    try {
      const response = await fetch(`http://localhost:8000/api/conversations/${conversationId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      });
      if (!response.ok) throw new Error('Failed to rename in database');
    } catch (e) {
      console.error('Database rename error', e);
      const local = this.getLocalConversations();
      const idx = local.findIndex(c => c.conversation_id === conversationId);
      if (idx > -1) {
        local[idx].title = title;
        this.saveLocalConversations(local);
      }
    }
  },

  // DELETE: Delete a conversation
  async deleteConversation(userId, conversationId) {
    if (!userId) {
      // Guest Mode: delete locally
      const local = this.getLocalConversations();
      const filtered = local.filter(c => c.conversation_id !== conversationId);
      this.saveLocalConversations(filtered);
      return;
    }

    try {
      const response = await fetch(`http://localhost:8000/api/conversations/${conversationId}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Failed to delete from database');
    } catch (e) {
      console.error('Database delete error', e);
      const local = this.getLocalConversations();
      const filtered = local.filter(c => c.conversation_id !== conversationId);
      this.saveLocalConversations(filtered);
    }
  }
};
