export function LoadingSpinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  };

  return (
    <div className="flex items-center justify-center p-8">
      <div
        className={`${sizeClasses[size]} animate-spin rounded-full border-2 border-gray-600 border-t-primary-400`}
      />
    </div>
  );
}

export function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <div className="h-12 w-12 animate-spin rounded-full border-2 border-gray-600 border-t-primary-400 mx-auto" />
        <p className="mt-4 text-gray-400">Loading...</p>
      </div>
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="bg-dark-surface border border-dark-border rounded-xl p-6 animate-pulse">
      <div className="h-4 bg-gray-700 rounded w-1/3 mb-4" />
      <div className="h-8 bg-gray-700 rounded w-2/3 mb-2" />
      <div className="h-3 bg-gray-700 rounded w-1/2" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-dark-surface border border-dark-border rounded-xl p-6 animate-pulse">
      <div className="h-4 bg-gray-700 rounded w-1/4 mb-6" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 mb-3">
          <div className="h-4 bg-gray-700 rounded flex-1" />
          <div className="h-4 bg-gray-700 rounded w-20" />
          <div className="h-4 bg-gray-700 rounded w-20" />
          <div className="h-4 bg-gray-700 rounded w-16" />
        </div>
      ))}
    </div>
  );
}
