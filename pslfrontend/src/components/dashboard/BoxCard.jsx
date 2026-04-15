// components/dashboard/BoxCard.js
import React from 'react';

const BoxCard = React.memo(({ title, count, icon, color = 'purple' }) => {
  const colorClasses = {
    purple: 'bg-purple-100 text-purple-800 border-purple-200',
    blue: 'bg-blue-100 text-blue-800 border-blue-200',
    indigo: 'bg-indigo-100 text-indigo-800 border-indigo-200',
    gray: 'bg-gray-100 text-gray-800 border-gray-200'
  };

  // Memoize the progress bar width calculation
  const progressWidth = React.useMemo(() => {
    const numCount = typeof count === 'string' && count === '...' ? 0 : parseInt(count) || 0;
    return `${Math.min(100, (numCount / 100) * 100)}%`;
  }, [count]);

  return (
    <div className={`p-6 rounded-xl border-2 ${colorClasses[color]} transition-all duration-200 hover:shadow-md`}>
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold">{title}</h3>
        {icon}
      </div>
      <p className="text-3xl font-bold">{count}</p>
      <div className="mt-4 h-2 bg-white rounded-full">
        <div 
          className={`h-2 rounded-full ${color === 'purple' ? 'bg-purple-400' : color === 'blue' ? 'bg-blue-400' : color === 'indigo' ? 'bg-indigo-400' : 'bg-gray-400'}`}
          style={{ width: progressWidth }}
        ></div>
      </div>
    </div>
  );
});

BoxCard.displayName = 'BoxCard';

export default BoxCard;