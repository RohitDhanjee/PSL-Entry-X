import React from 'react';
import { Smartphone, AlertCircle } from 'lucide-react';

const QRCodeDisplay = ({ qrCode }) => {
  if (!qrCode) {
    return (
      <div className="flex items-center justify-center p-8 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-gray-400 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No QR code available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Instructions */}
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 bg-emerald-100 rounded-full mb-3">
          <Smartphone className="w-6 h-6 text-emerald-600" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">
          Scan with your authenticator app
        </h3>
        <p className="text-sm text-gray-600">
          Use Google Authenticator, Authy, or any compatible app
        </p>
      </div>

      {/* QR Code */}
      <div className="flex justify-center p-6 bg-white border-2 border-gray-200 rounded-xl">
        <div className="relative">
          {/* QR Code Image */}
          <img
            src={qrCode}
            alt="2FA QR Code"
            className="w-64 h-64 rounded-lg"
          />
          
          {/* Corner decorations for visual appeal */}
          <div className="absolute -top-2 -left-2 w-4 h-4 border-t-2 border-l-2 border-emerald-600"></div>
          <div className="absolute -top-2 -right-2 w-4 h-4 border-t-2 border-r-2 border-emerald-600"></div>
          <div className="absolute -bottom-2 -left-2 w-4 h-4 border-b-2 border-l-2 border-emerald-600"></div>
          <div className="absolute -bottom-2 -right-2 w-4 h-4 border-b-2 border-r-2 border-emerald-600"></div>
        </div>
      </div>

      {/* App Recommendations */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <p className="text-sm font-medium text-blue-900 mb-2">
          Recommended Authenticator Apps:
        </p>
        <div className="grid grid-cols-2 gap-2 text-xs text-blue-800">
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 bg-blue-600 rounded-full"></div>
            <span>Google Authenticator</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 bg-blue-600 rounded-full"></div>
            <span>Microsoft Authenticator</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 bg-blue-600 rounded-full"></div>
            <span>Authy</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 bg-blue-600 rounded-full"></div>
            <span>1Password</span>
          </div>
        </div>
      </div>

      {/* Step-by-step guide */}
      <div className="bg-gray-50 rounded-lg p-4">
        <p className="text-sm font-medium text-gray-900 mb-3">How to scan:</p>
        <ol className="space-y-2 text-sm text-gray-700">
          <li className="flex gap-2">
            <span className="font-semibold text-emerald-600 min-w-[20px]">1.</span>
            <span>Open your authenticator app</span>
          </li>
          <li className="flex gap-2">
            <span className="font-semibold text-emerald-600 min-w-[20px]">2.</span>
            <span>Tap the "+" or "Add" button</span>
          </li>
          <li className="flex gap-2">
            <span className="font-semibold text-emerald-600 min-w-[20px]">3.</span>
            <span>Select "Scan QR Code" or "Scan Barcode"</span>
          </li>
          <li className="flex gap-2">
            <span className="font-semibold text-emerald-600 min-w-[20px]">4.</span>
            <span>Point your camera at the QR code above</span>
          </li>
        </ol>
      </div>
    </div>
  );
};

export default QRCodeDisplay; // ✅ MAKE SURE THIS LINE EXISTS