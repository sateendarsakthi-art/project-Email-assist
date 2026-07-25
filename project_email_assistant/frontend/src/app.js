import React, { useEffect, useState } from "react";
import axios from "axios";
import "./styles.css";

function App() {
  const [emails, setEmails] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [currentEmailIndex, setCurrentEmailIndex] = useState(0);
  const [isListening, setIsListening] = useState(false);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(null);

  useEffect(() => {
    loadEmails(1);
  }, []);

  const loadEmails = async (page = 1) => {
    try {
      const response = await axios.get("http://localhost:5000/emails", {
        params: {
          page: page,
          per_page: 5
        }
      });
      const data = response.data;
      if (page === 1) {
        setEmails(data.emails);
      } else {
        setEmails(prev => [...prev, ...data.emails]);
      }
      setCurrentPage(page);
      setTotalCount(data.total_count);
      setHasNext(data.has_next);
    } catch (error) {
      console.error("Error loading emails:", error);
    }
  };

  const loadNextEmails = () => {
    loadEmails(currentPage + 1);
  };

  const speak = (text, onEndCallback) => {
    const speech = new SpeechSynthesisUtterance(text);
    speech.rate = 0.9;
    if (onEndCallback) {
      speech.onend = onEndCallback;
    }
    window.speechSynthesis.speak(speech);
  };

  const markRead = async (id) => {
    try {
      await axios.post("http://localhost:5000/mark-read", { id });
      loadEmails();
    } catch (error) {
      console.error("Error marking email as read:", error);
    }
  };

  const readAllEmails = () => {
    if (emails.length > 0) {
      window.speechSynthesis.cancel();
      emails.forEach((email, index) => {
        const text = `Email ${index + 1} from ${email.sender}: ${email.summary}`;
        speak(text);
      });
    }
  };

  const readCurrentEmail = (index = currentEmailIndex) => {
    if (emails.length > 0 && index >= 0 && index < emails.length) {
      window.speechSynthesis.cancel();
      const email = emails[index];
      const text = `Email ${index + 1} from ${email.sender || "Unknown"}: ${email.summary}. Would you like to mark this email as read?`;
      
      setAwaitingConfirmation({
        action: "markRead",
        emailId: email.id,
        emailIndex: index
      });

      speak(text, () => {
        // Automatically start listening for yes/no confirmation after reading
        handleVoiceCommand();
      });
    }
  };

  const processCommand = (command) => {
    if (command.includes("fetch") || command.includes("load") || command.includes("get")) {
      loadEmails(1);
    } else if (command.includes("read all") || command.includes("read everything")) {
      readAllEmails();
    } else if (command.includes("read") || command.includes("summarize") || command.includes("open")) {
      // Check for specific numbers 1-5 in word or digit form
      const match = command.match(/\b(1|2|3|4|5|one|two|three|four|five)\b/);
      if (match) {
        const numMap = { "1": 0, "one": 0, "2": 1, "two": 1, "3": 2, "three": 2, "4": 3, "four": 3, "5": 4, "five": 4 };
        const index = numMap[match[1]];
        if (index !== undefined && index < emails.length) {
          setCurrentEmailIndex(index);
          readCurrentEmail(index);
        } else {
          speak(`Email ${match[1]} is not loaded.`);
        }
      } else {
        readCurrentEmail(currentEmailIndex);
      }
    } else if (command.includes("next")) {
      if (emails.length > 0) {
        const nextIndex = (currentEmailIndex + 1) % emails.length;
        setCurrentEmailIndex(nextIndex);
        readCurrentEmail(nextIndex);
      }
    } else if (command.includes("mark") || command.includes("read label")) {
      if (emails.length > 0) {
        markRead(emails[currentEmailIndex].id);
      }
    } else if (command.includes("stop") || command.includes("mute") || command.includes("cancel")) {
      window.speechSynthesis.cancel();
    } else if (command.includes("help") || command.includes("what can I say")) {
      speak("Available commands are: fetch, read all, read email 1 to 5, next, mark as read, stop, and help.");
    }
  };

  const handleVoiceButtonClick = (text) => {
    window.speechSynthesis.cancel();
    if (awaitingConfirmation && (text === "yes" || text === "no")) {
      if (text === "yes") {
        if (awaitingConfirmation.action === "markRead") {
          markRead(awaitingConfirmation.emailId);
          speak("Marked as read.");
        }
      } else {
        speak("Okay.");
      }
      setAwaitingConfirmation(null);
    } else {
      processCommand(text);
    }
  };

  const handleVoiceCommand = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Google Chrome or Safari.");
      return;
    }
    const recognition = new SpeechRecognition();
    setIsListening(true);

    recognition.start();

    recognition.onresult = (event) => {
      const command = event.results[0][0].transcript.toLowerCase();
      setIsListening(false);

      if (awaitingConfirmation) {
        if (command.includes("yes") || command.includes("yeah") || command.includes("sure")) {
          if (awaitingConfirmation.action === "markRead") {
            markRead(awaitingConfirmation.emailId);
            speak("Marked as read.");
          }
          setAwaitingConfirmation(null);
        } else if (command.includes("no") || command.includes("nope")) {
          speak("Okay.");
          setAwaitingConfirmation(null);
        } else {
          setAwaitingConfirmation(null);
          processCommand(command);
        }
      } else {
        processCommand(command);
      }
    };

    recognition.onerror = () => {
      setIsListening(false);
    };
  };

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA") {
        return;
      }
      if (e.code === "Space") {
        e.preventDefault();
        handleVoiceCommand();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [emails, currentEmailIndex, awaitingConfirmation]);

  const clearEmails = () => {
    setEmails([]);
    setCurrentPage(1);
    setTotalCount(0);
    setHasNext(false);
    setCurrentEmailIndex(0);
  };

  return (
    <div className="app-container">
      {/* Header */}
      <div className="header">
        <div className="header-left">
          <div className="logo">📧</div>
          <h1 className="logo-text">AI Email Assistant</h1>
        </div>
        <button className="gmail-btn">Gmail</button>
      </div>

      {/* Main Content */}
      <div className="main-content">
        {/* Inbox Section */}
        <div className="inbox-section">
          <h2 className="inbox-title">Your Inbox</h2>
          <p className="inbox-subtitle">AI-powered email summaries with voice control</p>

          {/* Voice Commands */}
          <div className={`voice-commands-section ${isListening ? "listening" : ""} ${awaitingConfirmation ? "confirming" : ""}`}>
            <div 
              className="voice-header" 
              onClick={handleVoiceCommand} 
              style={{ cursor: "pointer" }}
            >
              <span>
                {isListening 
                  ? "🎙️ LISTENING... (SPEAK NOW)" 
                  : awaitingConfirmation 
                    ? "❓ CONFIRM: MARK AS READ? (SAY YES OR NO)" 
                    : "🎤 VOICE COMMANDS (PRESS SPACE OR CLICK HERE)"}
              </span>
            </div>
            <div className="voice-buttons">
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("fetch emails")}>"fetch emails"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("read all emails")}>"read all emails"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("read email 1")}>"read email 1"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("next")}>"next"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("yes")}>"yes"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("no")}>"no"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("stop")}>"stop"</button>
              <button className="voice-btn" onClick={() => handleVoiceButtonClick("help")}>"help"</button>
            </div>
          </div>

          {/* Control Buttons */}
          <div className="control-buttons">
            <button 
              className="btn btn-primary" 
              onClick={() => loadEmails(1)}
            >
              📥 Fetch Emails
            </button>
            <button 
              className="btn btn-secondary" 
              onClick={readAllEmails}
            >
              🔊 Read All
            </button>
            <button 
              className="btn btn-secondary" 
              onClick={clearEmails}
            >
              Clear
            </button>
            {hasNext && (
              <button 
                className="btn btn-secondary" 
                onClick={loadNextEmails}
              >
                📬 Next 5
              </button>
            )}
            <span className="email-count">{emails.length} of {totalCount} emails</span>
          </div>

          {/* Emails List */}
          <div className="emails-list">
            {emails.map((email, index) => (
              <div key={email.id} className="email-item">
                <div className="email-left">
                  <div className="email-avatar">
                    {email.sender ? email.sender.charAt(0).toUpperCase() : "?"}
                  </div>
                  <div className="email-content">
                    <h3 className="email-subject">{email.subject || "No Subject"}</h3>
                    <p className="email-sender">{email.sender}</p>
                    <p className="email-preview">{email.summary}</p>
                  </div>
                </div>
                <div className="email-right">
                  <div className="email-status">
                    {email.read ? <span className="read-badge">✓ Read</span> : <span className="unread-badge">• Unread</span>}
                  </div>
                  <div className="email-actions">
                    <button className="btn-action" onClick={() => speak(email.summary)}>
                      🔊 Read Aloud
                    </button>
                    <button className="btn-action" onClick={() => markRead(email.id)}>
                      ✅ Mark as Read
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;