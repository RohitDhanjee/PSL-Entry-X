import React, { useState, useRef, useEffect } from 'react';
import { X, Shield, AlertCircle } from 'lucide-react';

const VerifyOTPModal = ({ isOpen, onClose, onVerify, loading }) => {
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [error, setError] = useState('');
  const inputRefs = useRef([]);

  useEffect(() => {
    if (isOpen && inputRefs.current[0]) {
      inputRefs.current[0].focus();
    }
  }, [isOpen]);

  const handleChange = (index, value) => {
    // Only allow numbers
    if (value && !/^\d$/.test(value)) {
      return;
    }

    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);
    setError('');

    // Auto-focus next input
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all fields are filled
    if (value && index === 5 && newOtp.every(digit => digit !== '')) {
      handleSubmit(newOtp.join(''));
    }
  };

  const handleKeyDown = (index, e) => {
    // Handle backspace
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }

    // Handle paste
    if (e.key === 'v' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      navigator.clipboard.readText().then(text => {
        const pastedDigits = text.replace(/\D/g, '').slice(0, 6).split('');
        const newOtp = [...otp];
        pastedDigits.forEach((digit, i) => {
          if (i < 6) {
            newOtp[i] = digit;
          }
        });
        setOtp(newOtp);
        
        // Focus last filled input or submit if complete
        const lastFilledIndex = newOtp.findIndex(d => !d);
        if (lastFilledIndex === -1) {
          handleSubmit(newOtp.join(''));
        } else {
          inputRefs.current[lastFilledIndex]?.focus();
        }
      });
    }

    // Handle Enter key
    if (e.key === 'Enter') {
      handleSubmit(otp.join(''));
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData('text');
    const pastedDigits = pastedData.replace(/\D/g, '').slice(0, 6).split('');
    
    const newOtp = [...otp];
    pastedDigits.forEach((digit, i) => {
      if (i < 6) {
        newOtp[i] = digit;
      }
    });
    setOtp(newOtp);

    // Focus appropriate input
    const lastFilledIndex = newOtp.findIndex(d => !d);
    if (lastFilledIndex === -1) {
      inputRefs.current[5]?.focus();
      handleSubmit(newOtp.join(''));
    } else {
      inputRefs.current[lastFilledIndex]?.focus();
    }
  };

  const handleSubmit = async (otpCode = null) => {
    const code = otpCode || otp.join('');
    
    if (code.length !== 6) {
      setError('Please enter all 6 digits');
      return;
    }

    try {
      await onVerify(code);
      // Success - modal will close from parent
    } catch (error) {
      setError('Invalid code. Please try again.');
      setOtp(['', '', '', '', '', '']);
      inputRefs.current[0]?.focus();
    }
  };

  const handleClose = () => {
    if (!loading) {
      setOtp(['', '', '', '', '', '']);
      setError('');
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black bg-opacity-50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-emerald-600 to-emerald-700 p-6 text-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-white bg-opacity-20 rounded-lg">
                <Shield className="w-6 h-6" />
              </div>
              <h2 className="text-2xl font-bold">Verify Code</h2>
            </div>
            <button
              onClick={handleClose}
              disabled={loading}
              className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors disabled:opacity-50"
            >
              <X className="w-6 h-6" />
            </button>
          </div>
          <p className="mt-2 text-emerald-100 text-sm">
            Enter the 6-digit code from your authenticator app
          </p>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* OTP Input */}
          <div className="space-y-2">
            <div className="flex justify-center gap-2">
              {otp.map((digit, index) => (
                <input
                  key={index}
                  ref={el => inputRefs.current[index] = el}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={e => handleChange(index, e.target.value)}
                  onKeyDown={e => handleKeyDown(index, e)}
                  onPaste={handlePaste}
                  disabled={loading}
                  className={`w-12 h-14 text-center text-2xl font-bold border-2 rounded-lg transition-all outline-none ${
                    error
                      ? 'border-red-500 bg-red-50'
                      : digit
                      ? 'border-emerald-600 bg-emerald-50'
                      : 'border-gray-300 hover:border-gray-400 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                />
              ))}
            </div>

            {/* Error Message */}
            {error && (
              <div className="flex items-center justify-center gap-2 text-red-600 text-sm">
                <AlertCircle className="w-4 h-4" />
                <span>{error}</span>
              </div>
            )}
          </div>

          {/* Instructions */}
          <div className="bg-gray-50 rounded-lg p-4 space-y-3">
            <p className="text-sm text-gray-700">
              <span className="font-medium">Tip:</span> You can paste the code directly from your clipboard
            </p>
            <div className="text-xs text-gray-600 space-y-1">
              <p>• The code refreshes every 30 seconds</p>
              <p>• Enter the current code shown in your authenticator app</p>
              <p>• Make sure your device time is synchronized</p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleClose}
              disabled={loading}
              className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={() => handleSubmit()}
              disabled={loading || otp.some(d => !d)}
              className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Verifying...</span>
                </>
              ) : (
                <>
                  <Shield className="w-5 h-5" />
                  <span>Verify</span>
                </>
              )}
            </button>
          </div>

          {/* Alternative verification */}
          <div className="text-center">
            <p className="text-xs text-gray-500">
              Lost access to your authenticator?{' '}
              <button className="text-emerald-600 hover:text-emerald-700 font-medium">
                Use backup code
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default VerifyOTPModal;

// This creates a beautiful OTP verification modal with:

// ✅ 6-digit OTP input with auto-focus
// ✅ Paste support (auto-fills all fields)
// ✅ Auto-submit when complete
// ✅ Keyboard navigation (backspace, enter)
// ✅ Visual feedback (colors, animations)
// ✅ Error handling
// ✅ Loading states

