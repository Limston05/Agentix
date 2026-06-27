import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatStorage } from './utils/storage';
import './App.css';

// Generating a unique ID for new chats
const generateId = () => `chat_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

const SYSTEM_LOGS = [
  "Initializing D2C Enterprise Operations Core...",
  "Retrieving local data schemas and constraints...",
  "Loading MongoDB abstraction adapters...",
  "Establishing Secure Sub-Agent Routing Protocols...",
  "SYSTEM ONLINE: Multi-Agent Network Active"
];

function App() {
  const [systemLogs, setSystemLogs] = useState([]);
  const [logsComplete, setLogsComplete] = useState(false);
  
  // Auth & Storage States
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('d2c_user');
    return saved ? JSON.parse(saved) : null;
  });
  
  const [conversations, setConversations] = useState([]);
  const [currentChatId, setCurrentChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  
  // UI Panels
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [customApiKey, setCustomApiKey] = useState(() => localStorage.getItem('d2c_provider_key') || '');
  const [searchQuery, setSearchQuery] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [isBannerVisible, setIsBannerVisible] = useState(true);
  
  // Loading & Reasoning States
  const [isLoading, setIsLoading] = useState(false);
  const [reasoningSteps, setReasoningSteps] = useState([]);
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  
  // Auth Form State
  const [emailInput, setEmailInput] = useState('');
  const [nameInput, setNameInput] = useState('');

  const chatEndRef = useRef(null);

  // 1. Initial terminal booting logs
  useEffect(() => {
    let currentLogIndex = 0;
    const interval = setInterval(() => {
      if (currentLogIndex < SYSTEM_LOGS.length) {
        setSystemLogs(prev => [...prev, SYSTEM_LOGS[currentLogIndex]]);
        currentLogIndex++;
      } else {
        clearInterval(interval);
        setTimeout(() => {
          setLogsComplete(true);
        }, 500);
      }
    }, 200);
    return () => clearInterval(interval);
  }, []);

  // 2. Load conversations list on auth change
  useEffect(() => {
    if (!logsComplete) return;
    
    const loadConversations = async () => {
      const list = await ChatStorage.getConversations(user?.user_id);
      setConversations(list);
      
      // Load most recent conversation if any exist, otherwise start a clean state
      if (list.length > 0) {
        const mostRecent = list[0];
        setCurrentChatId(mostRecent.conversation_id);
        setMessages(mostRecent.messages);
      } else {
        startNewChat();
      }
    };
    loadConversations();
  }, [user, logsComplete]);

  // 3. Auto-scroll mechanism
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // 4. Reasoning Panel ticks
  useEffect(() => {
    if (!isLoading || reasoningSteps.length === 0) return;

    const interval = setInterval(() => {
      setReasoningSteps(prev => {
        const next = [...prev];
        if (currentStepIdx < next.length) {
          if (currentStepIdx > 0) {
            next[currentStepIdx - 1].status = 'done';
          }
          next[currentStepIdx].status = 'active';
          setCurrentStepIdx(prevIdx => prevIdx + 1);
        } else {
          next[next.length - 1].status = 'done';
          clearInterval(interval);
        }
        return next;
      });
    }, 700);

    return () => clearInterval(interval);
  }, [isLoading, currentStepIdx, reasoningSteps]);

  // Start a fresh chat session
  const startNewChat = () => {
    setCurrentChatId(generateId());
    setMessages([]);
    setInput('');
  };

  // Switch between existing conversations
  const selectConversation = (id) => {
    const chat = conversations.find(c => c.conversation_id === id);
    if (chat) {
      setCurrentChatId(chat.conversation_id);
      setMessages(chat.messages);
    }
  };

  // Determine reasoning checklist based on prompt keywords
  const determineReasoningSteps = (text) => {
    const query = text.toLowerCase();
    if (query.includes('forecast') || query.includes('predict') || query.includes('demand')) {
      return [
        { id: 1, label: 'Routing query to Forecasting Engine', status: 'pending' },
        { id: 2, label: 'Analyzing stock parameters & category trends', status: 'pending' },
        { id: 3, label: 'Calculating time-series mathematical projection', status: 'pending' },
        { id: 4, label: 'Generating seasonal multiplier matrices', status: 'pending' }
      ];
    }
    if (query.includes('order') || query.includes('purchase') || query.includes('restock') || query.includes('po ') || query.includes('buy')) {
      return [
        { id: 1, label: 'Routing request to Operations sub-agent', status: 'pending' },
        { id: 2, label: 'Verifying SKU inventory coordinates', status: 'pending' },
        { id: 3, label: 'Drafting purchase order document variables', status: 'pending' },
        { id: 4, label: 'Writing transaction document to database collection', status: 'pending' }
      ];
    }
    // Default Analytical Search
    return [
      { id: 1, label: 'Routing request to Data Analyst sub-agent', status: 'pending' },
      { id: 2, label: 'Compiling query schema & filters mapping', status: 'pending' },
      { id: 3, label: 'Generating dynamic MongoDB MQL request', status: 'pending' },
      { id: 4, label: 'Executing dynamic collections extraction', status: 'pending' }
    ];
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setIsLoading(true);

    // Initialize reasoning visualizer steps
    const steps = determineReasoningSteps(userMessage);
    setReasoningSteps(steps);
    setCurrentStepIdx(0);

    const updatedMessages = [...messages, { role: 'user', content: userMessage }];
    setMessages(updatedMessages);

    try {
      const apiHistory = messages.map(msg => ({
        role: msg.role === 'user' ? 'user' : 'model',
        content: msg.content
      }));

      const headers = { 'Content-Type': 'application/json' };
      if (customApiKey.trim()) {
        headers['X-Provider-Key'] = customApiKey.trim();
      }

      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          message: userMessage,
          history: apiHistory,
          user_id: user?.user_id || null
        })
      });

      if (!response.ok) {
        let errorMsg = 'Cannot reach backend service';
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorMsg = errData.detail;
          }
        } catch (err) {}
        throw new Error(errorMsg);
      }

      const data = await response.json();
      
      const newModelMessage = {
        role: 'model',
        content: data.agent_reply,
        route: data.route
      };
      
      const finalMessages = [...updatedMessages, newModelMessage];
      setMessages(finalMessages);

      // Persist Conversation (Title is generated from first 4 words of initial user message)
      const chatTitle = conversations.find(c => c.conversation_id === currentChatId)?.title || 
                        userMessage.split(' ').slice(0, 5).join(' ') + '...';

      const conversationDoc = {
        conversation_id: currentChatId,
        user_id: user?.user_id || 'guest',
        title: chatTitle,
        messages: finalMessages
      };

      await ChatStorage.saveConversation(user?.user_id, conversationDoc);
      
      // Reload conversation list
      const updatedList = await ChatStorage.getConversations(user?.user_id);
      setConversations(updatedList);

    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, {
        role: 'model',
        content: `❌ **System Error**: ${err.message}. Please configure your API key in Settings if missing, or ensure FastAPI is running.`,
        route: 'ERROR'
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  // Delete Conversation
  const handleDeleteChat = async (e, id) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to delete this conversation?')) {
      await ChatStorage.deleteConversation(user?.user_id, id);
      const list = await ChatStorage.getConversations(user?.user_id);
      setConversations(list);
      if (currentChatId === id) {
        startNewChat();
      }
    }
  };

  // Rename Conversation
  const handleRenameChat = async (id, currentTitle) => {
    const newTitle = prompt('Enter a new title for this conversation:', currentTitle);
    if (newTitle && newTitle.trim()) {
      await ChatStorage.renameConversation(user?.user_id, id, newTitle.trim());
      const list = await ChatStorage.getConversations(user?.user_id);
      setConversations(list);
    }
  };

  // Mock Authentication Login
  const handleAuthSubmit = async (e, provider = 'Email') => {
    e.preventDefault();
    if (provider === 'Email' && (!emailInput.trim() || !nameInput.trim())) return;
    
    const email = emailInput.trim() || `${provider.toLowerCase()}@example.com`;
    const name = nameInput.trim() || `${provider} User`;

    try {
      const response = await fetch('http://localhost:8000/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, name, provider })
      });

      if (!response.ok) throw new Error('Authentication failed');
      const data = await response.json();
      
      setUser(data);
      localStorage.setItem('d2c_user', JSON.stringify(data));
      setShowAuthModal(false);
      setEmailInput('');
      setNameInput('');
    } catch (err) {
      alert(`Login failed: ${err.message}. Running backend in Guest mode fallback.`);
      // Mock login state locally if backend login fails
      const localData = {
        user_id: `USR_MOCK_${Date.now()}`,
        email,
        name,
        provider,
        token: 'mock-token'
      };
      setUser(localData);
      localStorage.setItem('d2c_user', JSON.stringify(localData));
      setShowAuthModal(false);
    }
  };

  // Log Out
  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem('d2c_user');
    startNewChat();
  };

  // Save Settings Modal API key
  const handleSaveSettings = (e) => {
    e.preventDefault();
    localStorage.setItem('d2c_provider_key', customApiKey.trim());
    setShowSettingsModal(false);
  };

  // Filter conversations based on query
  const filteredConversations = conversations.filter(c => 
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Suggested Prompts
  const suggestedPrompts = [
    { title: "Review Stock Levels", text: "Show inventory items with stock level below 200 units" },
    { title: "Forecast Demand", text: "Forecast demand for SKU-001 for the next 6 months" },
    { title: "Create Purchase Order", text: "Create a purchase order of 400 units for SKU-005" },
    { title: "Sales Analysis", text: "Show total order amount and dates grouped by category" }
  ];

  if (!logsComplete) {
    return (
      <div className="boot-container">
        <div className="boot-terminal">
          <div className="terminal-header">
            <span className="dot red"></span>
            <span className="dot yellow"></span>
            <span className="dot green"></span>
            <span className="terminal-title">D2C OPERATIONS OS TERMINAL</span>
          </div>
          <div className="terminal-body">
            {systemLogs.map((log, index) => (
              <div key={index} className="terminal-line">
                <span className="terminal-prompt">&gt;</span> {log}
              </div>
            ))}
            <div className="terminal-cursor"></div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`app-wrapper ${isSidebarOpen ? 'sidebar-expanded' : 'sidebar-collapsed'}`}>
      
      {/* Sidebar Backdrop for Mobile Overlay */}
      {isSidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setIsSidebarOpen(false)}></div>
      )}
      
      {/* Sidebar Panel */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <span className="logo-icon">📊</span>
            <h2>D2C Console</h2>
            <button className="close-sidebar-btn" onClick={() => setIsSidebarOpen(false)} title="Close Sidebar">
              ×
            </button>
          </div>
          <button className="new-chat-btn" onClick={startNewChat} title="Start a new chat session">
            <span>+</span> New Chat
          </button>
        </div>

        <div className="sidebar-search">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations..."
          />
        </div>

        <nav className="conversations-list">
          {filteredConversations.length > 0 ? (
            filteredConversations.map(conv => (
              <div
                key={conv.conversation_id}
                className={`conversation-item ${currentChatId === conv.conversation_id ? 'active' : ''}`}
                onClick={() => selectConversation(conv.conversation_id)}
              >
                <span className="chat-icon">💬</span>
                <span className="chat-title" title={conv.title}>{conv.title}</span>
                <div className="chat-actions">
                  <button onClick={(e) => { e.stopPropagation(); handleRenameChat(conv.conversation_id, conv.title); }} title="Rename">✏️</button>
                  <button onClick={(e) => handleDeleteChat(e, conv.conversation_id)} title="Delete">🗑️</button>
                </div>
              </div>
            ))
          ) : (
            <div className="no-chats">No conversations found</div>
          )}
        </nav>

        {/* User profile area */}
        <div className="sidebar-footer">
          {user ? (
            <div className="user-profile">
              <div className="user-avatar">{user.name[0].toUpperCase()}</div>
              <div className="user-info">
                <span className="user-name">{user.name}</span>
                <span className="user-email">{user.email}</span>
              </div>
              <button className="logout-btn" onClick={handleLogout} title="Log Out">Logout</button>
            </div>
          ) : (
            <div className="guest-footer">
              <button className="login-btn-sidebar" onClick={() => setShowAuthModal(true)}>
                Sign In / Register
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main chat layout */}
      <main className="main-content">
        <header className="main-header">
          <div className="header-left">
            <button className="toggle-sidebar-btn" onClick={() => setIsSidebarOpen(!isSidebarOpen)}>
              ☰
            </button>
            <div className="header-status">
              <span className="status-indicator"></span>
              <span>Enterprise Hub</span>
            </div>
          </div>

          <div className="header-actions">
            <button className="header-action-btn" onClick={() => setShowSettingsModal(true)}>
              ⚙️ Settings
            </button>
            {!user && (
              <button className="header-action-btn primary" onClick={() => setShowAuthModal(true)}>
                Sign In
              </button>
            )}
          </div>
        </header>

        {/* Sticky Banner Reminder for Guests */}
        {!user && isBannerVisible && (
          <div className="guest-reminder-banner">
            <span>💡 You are using D2C Console in Guest Mode. <strong>Sign in</strong> to sync and persist your conversation history across sessions and devices.</span>
            <div className="banner-actions">
              <button className="connect-btn" onClick={() => setShowAuthModal(true)}>Connect Account</button>
              <button className="close-banner-btn" onClick={() => setIsBannerVisible(false)} title="Dismiss">×</button>
            </div>
          </div>
        )}

        <div className="chat-scroll-area">
          <div className="chat-max-width">
            {messages.length === 0 ? (
              // Empty State - SaaS Onboarding Visuals
              <div className="onboarding-container">
                <div className="onboarding-header">
                  <h1>Multi-Agent Operations Interface</h1>
                  <p>Query operations logs, forecast inventory curves, and automate purchase orders using Gemini agents.</p>
                </div>

                <div className="onboarding-grid">
                  <div className="onboarding-card">
                    <div className="card-icon">🔍</div>
                    <h3>Dynamic Data Analysis</h3>
                    <p>Sub-Agent generates raw MongoDB queries to extract and summarize customer and sales metrics.</p>
                  </div>
                  <div className="onboarding-card">
                    <div className="card-icon">📈</div>
                    <h3>Demand Forecasting</h3>
                    <p>Mathematically predicts inventory trajectories based on SKU parameters and seasonality weights.</p>
                  </div>
                  <div className="onboarding-card">
                    <div className="card-icon">⚡</div>
                    <h3>Stock Restocking PO</h3>
                    <p>Authorizes operational sub-agents to commit restock PO documents to database tables.</p>
                  </div>
                </div>

                {/* Gemini API Key Onboarding & Rate Limits Guide */}
                <div className="api-guide-card">
                  <h3>🔑 Gemini API Onboarding & Rate Limits</h3>
                  <div className="api-guide-steps">
                    <div className="api-step">
                      <span className="step-num">1</span>
                      <p><strong>Obtain API Key:</strong> Visit <a href="https://aistudio.google.com/" target="_blank" rel="noopener noreferrer">Google AI Studio</a>, log in with your Google account, and click <strong>"Create API key"</strong>.</p>
                    </div>
                    <div className="api-step">
                      <span className="step-num">2</span>
                      <p><strong>Configuration:</strong> Click the <strong>⚙️ Settings</strong> button in the top-right header of this console and paste your key to activate multi-agent processing.</p>
                    </div>
                    <div className="api-step">
                      <span className="step-num">3</span>
                      <p><strong>Limits Warning:</strong> The free tier for Gemini 2.5 Flash enforces rate limits of <strong>15 Requests Per Minute (RPM)</strong> and <strong>1,500 Requests Per Day (RPD)</strong>.</p>
                    </div>
                    <div className="api-step">
                      <span className="step-num">4</span>
                      <p><strong>Quota Exhausted?</strong> If the console stops responding or throws a quota error, visit AI Studio using a <em>different Google account</em>, generate a new key, and update it in Settings.</p>
                    </div>
                  </div>
                </div>

                <div className="suggestions-section">
                  <h3>Suggested Inquiries</h3>
                  <div className="suggestions-grid">
                    {suggestedPrompts.map((prompt, idx) => (
                      <button key={idx} className="suggestion-chip" onClick={() => setInput(prompt.text)}>
                        <strong>{prompt.title}</strong>
                        <span>{prompt.text}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              // Active Conversation Bubbles
              <div className="chat-messages">
                {messages.map((msg, index) => (
                  <div key={index} className={`message-bubble-wrapper ${msg.role}`}>
                    <div className="message-header-details">
                      <span className="sender-tag">
                        {msg.role === 'user' ? 'Executive Director' : (
                          msg.route === 'ANALYTICAL' ? 'Data Analyst Agent' : 
                          msg.route === 'OPERATIONAL' ? 'Operations Agent' : 
                          msg.route === 'GENERAL' ? 'Supervisor Agent' : 'System Agent'
                        )}
                      </span>
                    </div>
                    <div className="message-body-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                ))}

                {/* Loading / Expanding Reasoning Visualizer */}
                {isLoading && (
                  <div className="reasoning-expander">
                    <div className="reasoning-header">
                      <div className="reasoning-title">
                        <span className="reasoning-pulse"></span>
                        Thinking Process...
                      </div>
                    </div>
                    <div className="reasoning-steps-list">
                      {reasoningSteps.map((step, idx) => (
                        <div key={step.id} className={`reasoning-step-item ${step.status}`}>
                          <span className="step-bullet">
                            {step.status === 'done' ? '✓' : step.status === 'active' ? '→' : '•'}
                          </span>
                          <span className="step-label">{step.label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
            )}
          </div>
        </div>

        {/* Input Bar Section */}
        <footer className="chat-input-bar">
          <div className="chat-max-width">
            <form onSubmit={handleSend} className="chat-input-form">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask D2C agents for metrics, forecasting, or PO creation..."
                disabled={isLoading}
              />
              <button type="submit" disabled={isLoading || !input.trim()}>
                Send
              </button>
            </form>
          </div>
        </footer>
      </main>

      {/* Authentication Modal */}
      {showAuthModal && (
        <div className="modal-overlay" onClick={() => setShowAuthModal(false)}>
          <div className="modal-card auth-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Connect D2C Account</h3>
              <button className="close-modal" onClick={() => setShowAuthModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <p className="modal-subtext">Access saved projects, sync historical sessions, and audit usage analytics.</p>
              
              <form onSubmit={(e) => handleAuthSubmit(e, 'Email')} className="email-auth-form">
                <div className="form-group">
                  <label>Full Name</label>
                  <input
                    type="text"
                    required
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    placeholder="Enter full name"
                  />
                </div>
                <div className="form-group">
                  <label>Email Address</label>
                  <input
                    type="email"
                    required
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="Enter email address"
                  />
                </div>
                <button type="submit" className="submit-auth-btn">
                  Sign In
                </button>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Settings Modal (Custom API Keys) */}
      {showSettingsModal && (
        <div className="modal-overlay" onClick={() => setShowSettingsModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>System Settings</h3>
              <button className="close-modal" onClick={() => setShowSettingsModal(false)}>×</button>
            </div>
            <form onSubmit={handleSaveSettings} className="modal-body">
              <p className="modal-subtext">By default, requests proxy through our secure backend. Optionally provide your own key below.</p>
              <div className="form-group">
                <label>Google GenAI API Key (Optional)</label>
                <input
                  type="password"
                  value={customApiKey}
                  onChange={(e) => setCustomApiKey(e.target.value)}
                  placeholder="Leave empty to use server API key"
                />
              </div>
              <div className="modal-footer">
                <button type="button" className="settings-btn secondary" onClick={() => setShowSettingsModal(false)}>Cancel</button>
                <button type="submit" className="settings-btn primary">Save Changes</button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

export default App;
