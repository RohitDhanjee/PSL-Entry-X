/**
 * PSL Entry X Gate Scanner
 * ================================
 * Scanner interface for security staff to validate dynamic QR codes.
 * 
 * Features:
 * - Real-time camera QR scanning (html5-qrcode)
 * - Anti-fraud verification with backend HMAC check
 * - Visual/Haptic feedback on scan status
 * - Automatic reset for next fan
 */

import React, { useState, useEffect, useRef } from "react";
import { 
  Shield, 
  Camera, 
  CheckCircle, 
  XCircle, 
  AlertTriangle, 
  Loader2, 
  ArrowLeft, 
  RefreshCw,
  Clock,
  UserCheck,
  Smartphone
} from "lucide-react";
import { Html5QrcodeScanner } from "html5-qrcode";
import { pslAPI } from "../../../services/api";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";

const GateScanner = () => {
  const navigate = useNavigate();
  const [scanResult, setScanResult] = useState(null);
  const [isValidating, setIsValidating] = useState(false);
  const [status, setStatus] = useState("idle"); // idle, validating, success, error, used
  const [message, setMessage] = useState("");
  const [lastTicketId, setLastTicketId] = useState("");
  const scannerRef = useRef(null);

  // Initialize Scanner
  useEffect(() => {
    const scanner = new Html5QrcodeScanner("reader", {
      fps: 10,
      qrbox: { width: 250, height: 250 },
      aspectRatio: 1.0,
      showTorchButtonIfSupported: true,
      rememberLastUsedCamera: true
    });

    scanner.render(onScanSuccess, onScanFailure);
    scannerRef.current = scanner;

    return () => {
      if (scannerRef.current) {
        scannerRef.current.clear().catch(err => console.error("Failed to clear scanner", err));
      }
    };
  }, []);

  // Handle successful scan
  const onScanSuccess = async (decodedText) => {
    if (status === "validating" || status === "success") return;

    // Expected format: PSL-ENTRY-X:{ticket_id}:{qr_hash}
    if (!decodedText.startsWith("PSL-ENTRY-X:")) {
      handleError("❌ Invalid QR Format. Not a PSL Entry X Secure Ticket.");
      return;
    }

    const parts = decodedText.split(":");
    if (parts.length < 3) {
      handleError("❌ QR Code Corrupted or Invalid");
      return;
    }

    const ticketId = parts[1];
    const qrHash = parts[2];

    // Check if we just scanned this ticket to prevent loops
    if (ticketId === lastTicketId && status === "success") return;

    validateTicket(ticketId, qrHash);
  };

  const onScanFailure = (error) => {
    // We ignore failures as they happen frequently during searching
    // console.debug("Scan failure", error);
  };

  const validateTicket = async (ticketId, qrHash) => {
    setStatus("validating");
    setIsValidating(true);
    setLastTicketId(ticketId);

    try {
      // In our API, license_id is often the same as ticket_id for the hash check or owner flow
      // The backend expects license_id as part of the hash verification
      const response = await pslAPI.validateTicket({
        ticket_id: ticketId,
        qr_hash: qrHash,
        license_id: ticketId // Using ticketId as fallback since licenseId isn't encoded in basic QR
      });

      if (response.data.is_valid) {
        handleSuccess(response.data.message || "✅ VALID TICKET");
      } else {
        const msg = response.data.message || "❌ INVALID QR CODE";
        if (msg.includes("already used") || msg.includes("redeemed")) {
          setStatus("used");
        } else {
          setStatus("error");
        }
        setMessage(msg);
        toast.error(msg);
      }
    } catch (err) {
      console.error("Validation error:", err);
      handleError(err.response?.data?.detail || "❌ Validation Failed");
    } finally {
      setIsValidating(false);
    }
  };

  const handleSuccess = (msg) => {
    setStatus("success");
    setMessage(msg);
    toast.success(msg, { duration: 4000 });
    
    // Play success sound if possible
    playStatusSound(true);

    // Reset after 4 seconds
    setTimeout(() => {
      resetScanner();
    }, 4000);
  };

  const handleError = (msg) => {
    setStatus("error");
    setMessage(msg);
    toast.error(msg);
    playStatusSound(false);

    // Reset after 3 seconds
    setTimeout(() => {
      resetScanner();
    }, 3000);
  };

  const resetScanner = () => {
    setStatus("idle");
    setMessage("");
    setScanResult(null);
  };

  const playStatusSound = (success) => {
    try {
      // Small beeps can be implemented with AudioContext for a more professional feel
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const oscillator = audioCtx.createOscillator();
      const gainNode = audioCtx.createGain();

      oscillator.connect(gainNode);
      gainNode.connect(audioCtx.destination);

      if (success) {
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(800, audioCtx.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(1200, audioCtx.currentTime + 0.1);
      } else {
        oscillator.type = 'square';
        oscillator.frequency.setValueAtTime(300, audioCtx.currentTime);
      }

      gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);

      oscillator.start();
      oscillator.stop(audioCtx.currentTime + 0.2);
    } catch (e) {
      console.warn("Audio feedback failed", e);
    }
  };

  return (
    <div className="min-h-[calc(100vh-100px)] max-w-lg mx-auto p-4 flex flex-col items-center">
      {/* Header */}
      <div className="w-full flex items-center justify-between mb-6">
        <button 
          onClick={() => navigate("/dashboard/psl-tickets")}
          className="p-2 hover:bg-gray-100 rounded-full transition-colors"
        >
          <ArrowLeft className="w-6 h-6 text-gray-600" />
        </button>
        <div className="flex flex-col items-center">
          <h1 className="text-xl font-bold text-gray-900">Gate Scanner</h1>
          <p className="text-xs text-green-600 font-semibold tracking-widest uppercase">PSL Entry X Gate</p>
        </div>
        <div className="w-10" /> {/* Spacer */}
      </div>

      {/* Security Status Banner */}
      <div className="w-full mb-6 p-3 bg-slate-900 rounded-2xl flex items-center gap-3 shadow-lg">
        <div className="p-2 bg-green-500/20 rounded-lg">
          <Shield className="w-5 h-5 text-green-500" />
        </div>
        <div>
          <p className="text-xs text-gray-400 font-medium">System Status</p>
          <p className="text-sm text-white font-semibold">Active & Secured</p>
        </div>
        <div className="ml-auto px-2 py-1 bg-green-500/10 border border-green-500/20 rounded-md">
          <span className="text-[10px] text-green-400 font-bold uppercase tracking-tighter">Live Monitor</span>
        </div>
      </div>

      {/* Scanner Container */}
      <div className="relative w-full aspect-square bg-slate-900 rounded-3xl overflow-hidden shadow-2xl border-4 border-slate-800">
        <div id="reader" className="w-full h-full"></div>
        
        {/* Validation Overlay */}
        {(status !== "idle") && (
          <div className={`absolute inset-0 z-[100] flex flex-col items-center justify-center backdrop-blur-md transition-all duration-300 ${
            status === "success" ? "bg-green-600/90" : 
            status === "error" ? "bg-red-600/90" : 
            status === "used" ? "bg-orange-600/90" : 
            "bg-blue-600/80"
          }`}>
            {status === "validating" && (
              <>
                <Loader2 className="w-16 h-16 text-white animate-spin mb-4" />
                <p className="text-white font-bold text-xl uppercase tracking-widest">Validating...</p>
              </>
            )}

            {status === "success" && (
              <>
                <div className="bg-white rounded-full p-4 mb-4 animate-bounce">
                  <CheckCircle className="w-20 h-20 text-green-600" />
                </div>
                <p className="text-white font-black text-3xl text-center px-6 leading-tight uppercase">
                  Welcome to <br /> the Match!
                </p>
                <div className="mt-6 flex items-center gap-2 px-4 py-2 bg-white/20 rounded-full">
                  <UserCheck className="w-5 h-5 text-white" />
                  <span className="text-white font-semibold text-sm">Entry Logged</span>
                </div>
              </>
            )}

            {(status === "error" || status === "used") && (
              <>
                <div className="bg-white rounded-full p-4 mb-4 animate-pulse">
                  <XCircle className={`w-20 h-20 ${status === "used" ? "text-orange-600" : "text-red-600"}`} />
                </div>
                <p className="text-white font-black text-3xl text-center px-6 leading-tight uppercase">
                  Entry <br /> Denied
                </p>
                <p className="mt-4 text-white text-sm font-medium bg-black/20 px-4 py-2 rounded-xl text-center mx-10">
                  {message}
                </p>
                <button 
                  onClick={resetScanner}
                  className="mt-8 px-6 py-2 bg-white text-gray-900 rounded-full font-bold flex items-center gap-2 hover:bg-gray-100 transition-colors"
                >
                  <RefreshCw className="w-4 h-4" />
                  Try Again
                </button>
              </>
            )}
          </div>
        )}

        {/* Scanning Frame (Only visible when idle) */}
        {status === "idle" && (
          <div className="absolute inset-0 pointer-events-none flex items-center justify-center z-50">
            <div className="w-64 h-64 border-2 border-green-500/30 rounded-2xl relative">
              {/* Corner markers */}
              <div className="absolute -top-1 -left-1 w-12 h-12 border-t-8 border-l-8 border-green-500 rounded-tl-2xl"></div>
              <div className="absolute -top-1 -right-1 w-12 h-12 border-t-8 border-r-8 border-green-500 rounded-tr-2xl"></div>
              <div className="absolute -bottom-1 -left-1 w-12 h-12 border-b-8 border-l-8 border-green-500 rounded-bl-2xl"></div>
              <div className="absolute -bottom-1 -right-1 w-12 h-12 border-b-8 border-r-8 border-green-500 rounded-br-2xl"></div>
              
              {/* Scan Line effect */}
              <div className="absolute top-0 left-0 right-0 h-1 bg-green-400 shadow-[0_0_20px_rgba(74,222,128,0.8)] animate-scan"></div>
            </div>
          </div>
        )}
      </div>

      {/* Instructions */}
      <div className="mt-8 w-full space-y-4">
        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-widest ml-1">Staff Instructions</h3>
        
        <div className="grid grid-cols-1 gap-3">
          <div className="p-4 bg-white border border-gray-100 rounded-2xl flex items-start gap-4 shadow-sm">
            <div className="p-2 bg-purple-50 rounded-lg">
              <Smartphone className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">Align QR Code</p>
              <p className="text-xs text-gray-500">Center the fan's digital pass within the markers above.</p>
            </div>
          </div>
          
          <div className="p-4 bg-white border border-gray-100 rounded-2xl flex items-start gap-4 shadow-sm">
            <div className="p-2 bg-amber-50 rounded-lg">
              <Clock className="w-5 h-5 text-amber-500" />
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">60-Second Check</p>
              <p className="text-xs text-gray-500">If the pass is expired, ask the fan to refresh their portal.</p>
            </div>
          </div>
        </div>
      </div>

      {/* Footer Info */}
      <div className="mt-12 text-center pb-8">
        <p className="text-[10px] text-gray-400 font-bold uppercase tracking-[0.3em]">
          PSL Entry X Security • Protocol v2.4
        </p>
      </div>

      <style>{`
        @keyframes scan {
          0% { top: 0%; }
          100% { top: 100%; }
        }
        .animate-scan {
          animation: scan 2s linear infinite;
        }
        /* HIDE LIBRARY DEFAULT UI */
        #reader {
          border: none !important;
          background: #0f172a !important;
        }
        #reader__status_span {
          display: none !important;
        }
        #reader__dashboard_section_csr button {
          background-color: #5b21b6 !important;
          color: white !important;
          border-radius: 99px !important;
          padding: 10px 24px !important;
          font-weight: 700 !important;
          border: none !important;
          text-transform: uppercase !important;
          letter-spacing: 0.1em !important;
          font-size: 12px !important;
          box-shadow: 0 10px 15px -3px rgba(139, 92, 246, 0.3) !important;
          margin: 10px auto !important;
        }
        #reader img {
           display: none !important;
        }
        #reader__header_message {
          display: none !important;
        }
        #reader__camera_selection {
          width: 80% !important;
          margin: 0 auto !important;
          padding: 8px !important;
          border-radius: 12px !important;
          border: 1px solid #334155 !important;
          background: #1e293b !important;
          color: white !important;
          font-size: 14px !important;
        }
        #reader__dashboard_section_swap_link {
           display: none !important;
        }
        #reader__dashboard_section_csr {
          display: flex !important;
          flex-direction: column !important;
          align-items: center !important;
          justify-content: center !important;
          height: 100% !important;
        }
        /* Custom video styling */
        video {
          border-radius: 20px !important;
          object-fit: cover !important;
          width: 100% !important;
          height: 100% !important;
          border: none !important;
        }
        /* Hide that small scan image text */
        #reader__dashboard_section_csr span {
           display: none !important;
        }
      `}</style>
    </div>
  );
};

export default GateScanner;
