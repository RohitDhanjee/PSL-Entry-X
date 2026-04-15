import React from 'react';
import { Link } from 'react-router-dom';

const Footer= () => {
  return (
    <footer className="bg-emerald-900 text-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="col-span-1">
            <h2 className="text-xl font-bold mb-4 tracking-wider uppercase">PSL Entry X</h2>
            <p className="text-emerald-100 mb-4">
              Secure, anti-scalping PSL Entry X smart tickets with dynamic entry passes powered by Wirefluid blockchain.
            </p>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-emerald-300 tracking-wider uppercase mb-4">
              PSL Entry X Portal
            </h3>
            <ul className="space-y-2">
              <li>
                <Link to="/explorer" className="text-emerald-100 hover:text-white">
                  PSL Entry X Explorer
                </Link>
              </li>
              <li>
                <Link to="/auth" className="text-emerald-100 hover:text-white">
                  PSL Entry X Login
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-emerald-300 tracking-wider uppercase mb-4">
              Matchday Support
            </h3>
            <ul className="space-y-2">
              <li>
                <a href="#" className="text-emerald-100 hover:text-white">
                  PSL Help Center
                </a>
              </li>
              <li>
                <a href="#" className="text-emerald-100 hover:text-white">
                  Matchday Entry Guide
                </a>
              </li>
            </ul>
          </div>
        </div>
        <div className="mt-8 pt-8 border-t border-emerald-800">
          <p className="text-emerald-200 text-sm text-center">
            &copy; {new Date().getFullYear()} PSL Entry X. Built for Wirefluid Hackathon 2026.
          </p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;