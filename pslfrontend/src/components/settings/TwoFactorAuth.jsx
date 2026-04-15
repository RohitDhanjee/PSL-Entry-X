// import React, { useState, useEffect } from 'react';
// import { X, Smartphone, AlertCircle, CheckCircle, Shield, Copy, Download } from 'lucide-react';
// import { authAPI } from '../../services/api';
// import toast from 'react-hot-toast';
// import QRCodeDisplay from './QRCodeDisplay';
// import VerifyOTPModal from './VerifyOTPModal';

// const TwoFactorAuth = ({ isOpen, onClose, isEnabled, onStatusChange }) => {
//   const [step, setStep] = useState('initial'); // initial, setup, verify, disable
//   const [qrCode, setQrCode] = useState(null);
//   const [secret, setSecret] = useState(null);
//   const [backupCodes, setBackupCodes] = useState([]);
//   const [loading, setLoading] = useState(false);
//   const [showVerifyModal, setShowVerifyModal] = useState(false);
//   const [disablePassword, setDisablePassword] = useState('');

//   useEffect(() => {
//     if (isOpen) {
//       if (isEnabled) {
//         setStep('disable');
//       } else {
//         setStep('initial');
//       }
//     }
//   }, [isOpen, isEnabled]);

//   // Enable 2FA - Step 1: Get QR Code
//   const handleEnable2FA = async () => {
//     setLoading(true);
//     try {
//       const response = await authAPI.enable2FA();
      
//       if (response.qr_code && response.secret) {
//         setQrCode(response.qr_code);
//         setSecret(response.secret);
//         setStep('setup');
//         toast.success('QR code generated! Scan it with your authenticator app.');
//       } else {
//         throw new Error('Failed to generate QR code');
//       }
//     } catch (error) {
//       console.error('Failed to enable 2FA:', error);
//       toast.error(error.message || 'Failed to enable 2FA. Please try again.');
//     } finally {
//       setLoading(false);
//     }
//   };

//   // Enable 2FA - Step 2: Verify OTP
//   const handleVerifySetup = async (otpCode) => {
//     setLoading(true);
//     try {
//       const response = await authAPI.verify2FASetup(otpCode);
      
//       if (response.success) {
//         // Generate backup codes
//         const backupResponse = await authAPI.generateBackupCodes();
//         setBackupCodes(backupResponse.backup_codes || []);
        
//         setStep('backup-codes');
//         toast.success('2FA enabled successfully!', {
//           icon: '🔐',
//           duration: 3000,
//         });
//       } else {
//         throw new Error('Verification failed');
//       }
//     } catch (error) {
//       console.error('Failed to verify 2FA setup:', error);
//       toast.error(error.message || 'Invalid verification code. Please try again.');
//       throw error; // Re-throw to keep modal open
//     } finally {
//       setLoading(false);
//     }
//   };

//   // Disable 2FA
//   const handleDisable2FA = async () => {
//     if (!disablePassword) {
//       toast.error('Please enter your password to disable 2FA');
//       return;
//     }

//     setLoading(true);
//     try {
//       const response = await authAPI.disable2FA(disablePassword);
      
//       if (response.success) {
//         toast.success('2FA disabled successfully');
//         onStatusChange(false);
//         onClose();
//       } else {
//         throw new Error('Failed to disable 2FA');
//       }
//     } catch (error) {
//       console.error('Failed to disable 2FA:', error);
//       toast.error(error.message || 'Failed to disable 2FA. Please check your password.');
//     } finally {
//       setLoading(false);
//     }
//   };

//   const handleCopySecret = () => {
//     if (secret) {
//       navigator.clipboard.writeText(secret);
//       toast.success('Secret key copied to clipboard!');
//     }
//   };

//   const handleCopyBackupCodes = () => {
//     if (backupCodes.length > 0) {
//       const codesText = backupCodes.join('\n');
//       navigator.clipboard.writeText(codesText);
//       toast.success('Backup codes copied to clipboard!');
//     }
//   };

//   const handleDownloadBackupCodes = () => {
//     if (backupCodes.length > 0) {
//       const codesText = backupCodes.join('\n');
//       const blob = new Blob([codesText], { type: 'text/plain' });
//       const url = URL.createObjectURL(blob);
//       const a = document.createElement('a');
//       a.href = url;
//       a.download = 'psl-entry-x-2fa-backup-codes.txt';
//       document.body.appendChild(a);
//       a.click();
//       document.body.removeChild(a);
//       URL.revokeObjectURL(url);
//       toast.success('Backup codes downloaded!');
//     }
//   };

//   const handleComplete = () => {
//     onStatusChange(true);
//     onClose();
//   };

//   const handleCancel = () => {
//     setStep('initial');
//     setQrCode(null);
//     setSecret(null);
//     setBackupCodes([]);
//     setDisablePassword('');
//     onClose();
//   };

//   if (!isOpen) return null;

//   return (
//     <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50 backdrop-blur-sm">
//       <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden max-h-[90vh] overflow-y-auto">
//         {/* Initial Step - Enable 2FA */}
//         {step === 'initial' && (
//           <>
//             <div className="bg-gradient-to-r from-emerald-600 to-emerald-700 p-6 text-white">
//               <div className="flex items-center justify-between">
//                 <div className="flex items-center gap-3">
//                   <div className="p-2 bg-white bg-opacity-20 rounded-lg">
//                     <Shield className="w-6 h-6" />
//                   </div>
//                   <h2 className="text-2xl font-bold">Enable Two-Factor Authentication</h2>
//                 </div>
//                 <button
//                   onClick={handleCancel}
//                   className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
//                 >
//                   <X className="w-6 h-6" />
//                 </button>
//               </div>
//             </div>

//             <div className="p-6 space-y-4">
//               <div className="flex items-start gap-3 p-4 bg-blue-50 border border-blue-200 rounded-lg">
//                 <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
//                 <div className="text-sm text-blue-800">
//                   <p className="font-medium mb-1">What you'll need:</p>
//                   <ul className="list-disc list-inside space-y-1">
//                     <li>An authenticator app (Google Authenticator, Authy, etc.)</li>
//                     <li>Your smartphone or tablet</li>
//                     <li>A few minutes to complete the setup</li>
//                   </ul>
//                 </div>
//               </div>

//               <div className="space-y-3">
//                 <h3 className="font-semibold text-gray-900">How it works:</h3>
//                 <ol className="space-y-2 text-sm text-gray-700">
//                   <li className="flex gap-2">
//                     <span className="font-bold text-emerald-600">1.</span>
//                     <span>We'll generate a QR code for your authenticator app</span>
//                   </li>
//                   <li className="flex gap-2">
//                     <span className="font-bold text-emerald-600">2.</span>
//                     <span>Scan the QR code with your authenticator app</span>
//                   </li>
//                   <li className="flex gap-2">
//                     <span className="font-bold text-emerald-600">3.</span>
//                     <span>Enter the 6-digit code to verify</span>
//                   </li>
//                   <li className="flex gap-2">
//                     <span className="font-bold text-emerald-600">4.</span>
//                     <span>Save your backup codes in a safe place</span>
//                   </li>
//                 </ol>
//               </div>

//               <div className="flex gap-3 pt-4">
//                 <button
//                   onClick={handleCancel}
//                   className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors"
//                 >
//                   Cancel
//                 </button>
//                 <button
//                   onClick={handleEnable2FA}
//                   disabled={loading}
//                   className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
//                 >
//                   {loading ? (
//                     <>
//                       <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
//                       <span>Setting up...</span>
//                     </>
//                   ) : (
//                     <>
//                       <Shield className="w-5 h-5" />
//                       <span>Get Started</span>
//                     </>
//                   )}
//                 </button>
//               </div>
//             </div>
//           </>
//         )}

//         {/* Setup Step - Show QR Code */}
//         {step === 'setup' && qrCode && secret && (
//           <>
//             <div className="bg-gradient-to-r from-emerald-600 to-emerald-700 p-6 text-white">
//               <div className="flex items-center justify-between">
//                 <div className="flex items-center gap-3">
//                   <div className="p-2 bg-white bg-opacity-20 rounded-lg">
//                     <Smartphone className="w-6 h-6" />
//                   </div>
//                   <h2 className="text-2xl font-bold">Scan QR Code</h2>
//                 </div>
//                 <button
//                   onClick={handleCancel}
//                   disabled={loading}
//                   className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
//                 >
//                   <X className="w-6 h-6" />
//                 </button>
//               </div>
//             </div>

//             <div className="p-6 space-y-4">
//               <QRCodeDisplay qrCode={qrCode} />

//               <div className="space-y-2">
//                 <p className="text-sm font-medium text-gray-700">
//                   Can't scan the QR code? Enter this key manually:
//                 </p>
//                 <div className="flex items-center gap-2">
//                   <code className="flex-1 px-3 py-2 bg-gray-100 rounded-lg text-sm font-mono break-all">
//                     {secret}
//                   </code>
//                   <button
//                     onClick={handleCopySecret}
//                     className="p-2 text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors"
//                     title="Copy secret key"
//                   >
//                     <Copy className="w-5 h-5" />
//                   </button>
//                 </div>
//               </div>

//               <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
//                 <div className="flex gap-2">
//                   <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
//                   <p className="text-sm text-yellow-800">
//                     After scanning, enter the 6-digit code from your authenticator app to complete setup.
//                   </p>
//                 </div>
//               </div>

//               <div className="flex gap-3 pt-2">
//                 <button
//                   onClick={handleCancel}
//                   disabled={loading}
//                   className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors"
//                 >
//                   Cancel
//                 </button>
//                 <button
//                   onClick={() => setShowVerifyModal(true)}
//                   disabled={loading}
//                   className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors"
//                 >
//                   Enter Code
//                 </button>
//               </div>
//             </div>
//           </>
//         )}

//         {/* Backup Codes Step */}
//         {step === 'backup-codes' && (
//           <>
//             <div className="bg-gradient-to-r from-green-600 to-green-700 p-6 text-white">
//               <div className="flex items-center justify-between">
//                 <div className="flex items-center gap-3">
//                   <div className="p-2 bg-white bg-opacity-20 rounded-lg">
//                     <CheckCircle className="w-6 h-6" />
//                   </div>
//                   <h2 className="text-2xl font-bold">2FA Enabled Successfully!</h2>
//                 </div>
//               </div>
//             </div>

//             <div className="p-6 space-y-4">
//               <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
//                 <div className="flex gap-2">
//                   <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
//                   <div className="text-sm text-red-800">
//                     <p className="font-medium mb-1">Save your backup codes!</p>
//                     <p>
//                       These codes can be used to access your account if you lose access to your authenticator app.
//                       Store them in a safe place.
//                     </p>
//                   </div>
//                 </div>
//               </div>

//               <div className="space-y-2">
//                 <p className="text-sm font-medium text-gray-700">Your Backup Codes:</p>
//                 <div className="p-4 bg-gray-100 rounded-lg">
//                   <div className="grid grid-cols-2 gap-2 font-mono text-sm">
//                     {backupCodes.map((code, index) => (
//                       <div key={index} className="text-gray-800">
//                         {code}
//                       </div>
//                     ))}
//                   </div>
//                 </div>
//               </div>

//               <div className="flex gap-2">
//                 <button
//                   onClick={handleCopyBackupCodes}
//                   className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
//                 >
//                   <Copy className="w-4 h-4" />
//                   Copy Codes
//                 </button>
//                 <button
//                   onClick={handleDownloadBackupCodes}
//                   className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
//                 >
//                   <Download className="w-4 h-4" />
//                   Download
//                 </button>
//               </div>

//               <button
//                 onClick={handleComplete}
//                 className="w-full px-4 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
//               >
//                 I've Saved My Backup Codes
//               </button>
//             </div>
//           </>
//         )}

//         {/* Disable 2FA Step */}
//         {step === 'disable' && (
//           <>
//             <div className="bg-gradient-to-r from-red-600 to-red-700 p-6 text-white">
//               <div className="flex items-center justify-between">
//                 <div className="flex items-center gap-3">
//                   <div className="p-2 bg-white bg-opacity-20 rounded-lg">
//                     <AlertCircle className="w-6 h-6" />
//                   </div>
//                   <h2 className="text-2xl font-bold">Disable Two-Factor Authentication</h2>
//                 </div>
//                 <button
//                   onClick={handleCancel}
//                   disabled={loading}
//                   className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
//                 >
//                   <X className="w-6 h-6" />
//                 </button>
//               </div>
//             </div>

//             <div className="p-6 space-y-4">
//               <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
//                 <div className="flex gap-2">
//                   <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
//                   <div className="text-sm text-red-800">
//                     <p className="font-medium mb-1">Warning!</p>
//                     <p>
//                       Disabling 2FA will make your account less secure. You'll only need your password to log in.
//                     </p>
//                   </div>
//                 </div>
//               </div>

//               <div>
//                 <label className="block text-sm font-medium text-gray-700 mb-2">
//                   Enter your password to confirm
//                 </label>
//                 <input
//                   type="password"
//                   value={disablePassword}
//                   onChange={(e) => setDisablePassword(e.target.value)}
//                   className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent outline-none"
//                   placeholder="Enter your password"
//                   disabled={loading}
//                 />
//               </div>

//               <div className="flex gap-3 pt-2">
//                 <button
//                   onClick={handleCancel}
//                   disabled={loading}
//                   className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors"
//                 >
//                   Cancel
//                 </button>
//                 <button
//                   onClick={handleDisable2FA}
//                   disabled={loading || !disablePassword}
//                   className="flex-1 px-4 py-3 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
//                 >
//                   {loading ? (
//                     <>
//                       <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
//                       <span>Disabling...</span>
//                     </>
//                   ) : (
//                     <>
//                       <AlertCircle className="w-5 h-5" />
//                       <span>Disable 2FA</span>
//                     </>
//                   )}
//                 </button>
//               </div>
//             </div>
//           </>
//         )}
//       </div>

//       {/* Verify OTP Modal */}
//       {showVerifyModal && (
//         <VerifyOTPModal
//           isOpen={showVerifyModal}
//           onClose={() => setShowVerifyModal(false)}
//           onVerify={handleVerifySetup}
//           loading={loading}
//         />
//       )}
//     </div>
//   );
// };

// export default TwoFactorAuth;

// // This creates the full 2FA management component with:

// // ✅ Enable 2FA flow (initial → setup → verify → backup codes)
// // ✅ Disable 2FA with password confirmation
// // ✅ QR code display
// // ✅ Backup codes generation & download
// // ✅ Step-by-step wizard

import React, { useState, useEffect } from 'react';
import { X, Smartphone, AlertCircle, CheckCircle, Shield, Copy, Download } from 'lucide-react';
import { authAPI } from '../../services/api';
import toast from 'react-hot-toast';
import QRCodeDisplay from './QRCodeDisplay';
import VerifyOTPModal from './VerifyOTPModal';

const TwoFactorAuth = ({ isOpen, onClose, isEnabled, onStatusChange }) => {
  const [step, setStep] = useState('initial'); // initial, setup, verify, disable
  const [qrCode, setQrCode] = useState(null);
  const [secret, setSecret] = useState(null);
  const [backupCodes, setBackupCodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showVerifyModal, setShowVerifyModal] = useState(false);
  const [disablePassword, setDisablePassword] = useState('');

  useEffect(() => {
    if (isOpen) {
      if (isEnabled) {
        setStep('disable');
      } else {
        setStep('initial');
      }
    }
  }, [isOpen, isEnabled]);

  // Enable 2FA - Step 1: Get QR Code
  const handleEnable2FA = async () => {
    setLoading(true);
    try {
      const response = await authAPI.enable2FA();
      
      if (response.qr_code && response.secret) {
        setQrCode(response.qr_code);
        setSecret(response.secret);
        setStep('setup');
        toast.success('QR code generated! Scan it with your authenticator app.');
      } else {
        throw new Error('Failed to generate QR code');
      }
    } catch (error) {
      console.error('Failed to enable 2FA:', error);
      toast.error(error.message || 'Failed to enable 2FA. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // ✅ UPDATED: Enable 2FA - Step 2: Verify OTP with auto-close
  const handleVerifySetup = async (otpCode) => {
    setLoading(true);
    try {
      const response = await authAPI.verify2FASetup(otpCode);
      
      if (response.success) {
        // Generate backup codes
        const backupResponse = await authAPI.generateBackupCodes();
        setBackupCodes(backupResponse.backup_codes || []);
        
        setStep('backup-codes');
        
        // ✅ Close the verify modal immediately
        setShowVerifyModal(false);
        
        toast.success('2FA enabled successfully!', {
          icon: '🔐',
          duration: 3000,
        });
      } else {
        throw new Error('Verification failed');
      }
    } catch (error) {
      console.error('Failed to verify 2FA setup:', error);
      toast.error(error.message || 'Invalid verification code. Please try again.');
      throw error; // Re-throw to keep modal open
    } finally {
      setLoading(false);
    }
  };

  // ✅ UPDATED: Disable 2FA with auto-close
  const handleDisable2FA = async () => {
    if (!disablePassword) {
      toast.error('Please enter your password to disable 2FA');
      return;
    }

    setLoading(true);
    try {
      const response = await authAPI.disable2FA(disablePassword);
      
      if (response.success) {
        toast.success('2FA disabled successfully');
        onStatusChange(false);
        
        // ✅ AUTO-CLOSE: Wait 1 second then close
        setTimeout(() => {
          onClose();
        }, 1000);
      } else {
        throw new Error('Failed to disable 2FA');
      }
    } catch (error) {
      console.error('Failed to disable 2FA:', error);
      toast.error(error.message || 'Failed to disable 2FA. Please check your password.');
    } finally {
      setLoading(false);
    }
  };

  const handleCopySecret = () => {
    if (secret) {
      navigator.clipboard.writeText(secret);
      toast.success('Secret key copied to clipboard!');
    }
  };

  const handleCopyBackupCodes = () => {
    if (backupCodes.length > 0) {
      const codesText = backupCodes.join('\n');
      navigator.clipboard.writeText(codesText);
      toast.success('Backup codes copied to clipboard!');
    }
  };

  const handleDownloadBackupCodes = () => {
    if (backupCodes.length > 0) {
      const codesText = backupCodes.join('\n');
      const blob = new Blob([codesText], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'psl-entry-x-2fa-backup-codes.txt';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success('Backup codes downloaded!');
    }
  };

  // ✅ UPDATED: Complete with auto-close
  const handleComplete = () => {
    onStatusChange(true);
    
    // ✅ AUTO-CLOSE: Wait 500ms then close
    setTimeout(() => {
      onClose();
    }, 500);
  };

  // ✅ UPDATED: Cancel with cleanup
  const handleCancel = () => {
    setStep('initial');
    setQrCode(null);
    setSecret(null);
    setBackupCodes([]);
    setDisablePassword('');
    setShowVerifyModal(false); // ✅ Close verify modal if open
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden max-h-[90vh] overflow-y-auto">
        {/* Initial Step - Enable 2FA */}
        {step === 'initial' && (
          <>
            <div className="bg-gradient-to-r from-emerald-600 to-emerald-700 p-6 text-white">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-white bg-opacity-20 rounded-lg">
                    <Shield className="w-6 h-6" />
                  </div>
                  <h2 className="text-2xl font-bold">Enable Two-Factor Authentication</h2>
                </div>
                <button
                  onClick={handleCancel}
                  className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>
            </div>

            <div className="p-6 space-y-4">
              <div className="flex items-start gap-3 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-blue-800">
                  <p className="font-medium mb-1">What you'll need:</p>
                  <ul className="list-disc list-inside space-y-1">
                    <li>An authenticator app (Google Authenticator, Authy, etc.)</li>
                    <li>Your smartphone or tablet</li>
                    <li>A few minutes to complete the setup</li>
                  </ul>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="font-semibold text-gray-900">How it works:</h3>
                <ol className="space-y-2 text-sm text-gray-700">
                  <li className="flex gap-2">
                    <span className="font-bold text-emerald-600">1.</span>
                    <span>We'll generate a QR code for your authenticator app</span>
                  </li>
                  <li className="flex gap-2">
                    <span className="font-bold text-emerald-600">2.</span>
                    <span>Scan the QR code with your authenticator app</span>
                  </li>
                  <li className="flex gap-2">
                    <span className="font-bold text-emerald-600">3.</span>
                    <span>Enter the 6-digit code to verify</span>
                  </li>
                  <li className="flex gap-2">
                    <span className="font-bold text-emerald-600">4.</span>
                    <span>Save your backup codes in a safe place</span>
                  </li>
                </ol>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  onClick={handleCancel}
                  className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleEnable2FA}
                  disabled={loading}
                  className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <>
                      <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      <span>Setting up...</span>
                    </>
                  ) : (
                    <>
                      <Shield className="w-5 h-5" />
                      <span>Get Started</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </>
        )}

        {/* Setup Step - Show QR Code */}
        {step === 'setup' && qrCode && secret && (
          <>
            <div className="bg-gradient-to-r from-emerald-600 to-emerald-700 p-6 text-white">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-white bg-opacity-20 rounded-lg">
                    <Smartphone className="w-6 h-6" />
                  </div>
                  <h2 className="text-2xl font-bold">Scan QR Code</h2>
                </div>
                <button
                  onClick={handleCancel}
                  disabled={loading}
                  className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>
            </div>

            <div className="p-6 space-y-4">
              <QRCodeDisplay qrCode={qrCode} />

              <div className="space-y-2">
                <p className="text-sm font-medium text-gray-700">
                  Can't scan the QR code? Enter this key manually:
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 px-3 py-2 bg-gray-100 rounded-lg text-sm font-mono break-all">
                    {secret}
                  </code>
                  <button
                    onClick={handleCopySecret}
                    className="p-2 text-emerald-600 hover:bg-emerald-50 rounded-lg transition-colors"
                    title="Copy secret key"
                  >
                    <Copy className="w-5 h-5" />
                  </button>
                </div>
              </div>

              <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                <div className="flex gap-2">
                  <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-yellow-800">
                    After scanning, enter the 6-digit code from your authenticator app to complete setup.
                  </p>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleCancel}
                  disabled={loading}
                  className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => setShowVerifyModal(true)}
                  disabled={loading}
                  className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors"
                >
                  Enter Code
                </button>
              </div>
            </div>
          </>
        )}

        {/* Backup Codes Step */}
        {step === 'backup-codes' && (
          <>
            <div className="bg-gradient-to-r from-green-600 to-green-700 p-6 text-white">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-white bg-opacity-20 rounded-lg">
                    <CheckCircle className="w-6 h-6" />
                  </div>
                  <h2 className="text-2xl font-bold">2FA Enabled Successfully!</h2>
                </div>
              </div>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <div className="flex gap-2">
                  <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div className="text-sm text-red-800">
                    <p className="font-medium mb-1">Save your backup codes!</p>
                    <p>
                      These codes can be used to access your account if you lose access to your authenticator app.
                      Store them in a safe place.
                    </p>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium text-gray-700">Your Backup Codes:</p>
                <div className="p-4 bg-gray-100 rounded-lg">
                  <div className="grid grid-cols-2 gap-2 font-mono text-sm">
                    {backupCodes.map((code, index) => (
                      <div key={index} className="text-gray-800">
                        {code}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={handleCopyBackupCodes}
                  className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
                >
                  <Copy className="w-4 h-4" />
                  Copy Codes
                </button>
                <button
                  onClick={handleDownloadBackupCodes}
                  className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
                >
                  <Download className="w-4 h-4" />
                  Download
                </button>
              </div>

              <button
                onClick={handleComplete}
                className="w-full px-4 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
              >
                I've Saved My Backup Codes
              </button>
            </div>
          </>
        )}

        {/* Disable 2FA Step */}
        {step === 'disable' && (
          <>
            <div className="bg-gradient-to-r from-red-600 to-red-700 p-6 text-white">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-white bg-opacity-20 rounded-lg">
                    <AlertCircle className="w-6 h-6" />
                  </div>
                  <h2 className="text-2xl font-bold">Disable Two-Factor Authentication</h2>
                </div>
                <button
                  onClick={handleCancel}
                  disabled={loading}
                  className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <div className="flex gap-2">
                  <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div className="text-sm text-red-800">
                    <p className="font-medium mb-1">Warning!</p>
                    <p>
                      Disabling 2FA will make your account less secure. You'll only need your password to log in.
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Enter your password to confirm
                </label>
                <input
                  type="password"
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent outline-none"
                  placeholder="Enter your password"
                  disabled={loading}
                  onKeyPress={(e) => {
                    // ✅ NEW: Submit on Enter key
                    if (e.key === 'Enter' && disablePassword) {
                      handleDisable2FA();
                    }
                  }}
                />
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleCancel}
                  disabled={loading}
                  className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDisable2FA}
                  disabled={loading || !disablePassword}
                  className="flex-1 px-4 py-3 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <>
                      <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      <span>Disabling...</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle className="w-5 h-5" />
                      <span>Disable 2FA</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Verify OTP Modal */}
      {showVerifyModal && (
        <VerifyOTPModal
          isOpen={showVerifyModal}
          onClose={() => setShowVerifyModal(false)}
          onVerify={handleVerifySetup}
          loading={loading}
        />
      )}
    </div>
  );
};

export default TwoFactorAuth;