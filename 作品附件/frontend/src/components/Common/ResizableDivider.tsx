import { useState, useRef, useCallback, useEffect } from 'react';

interface ResizableDividerProps {
  onResize: (delta: number) => void;
  className?: string;
}

export function ResizableDivider({ onResize, className = '' }: ResizableDividerProps) {
  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startXRef.current = e.clientX;
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      const delta = e.clientX - startXRef.current;
      onResize(delta);
      startXRef.current = e.clientX;
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, onResize]);

  return (
    <div
      className={`w-1 cursor-col-resize flex items-center justify-center transition-colors duration-150 ${className} ${
        isDragging ? 'bg-accent-blue' : 'bg-border-default hover:bg-accent-blue/50'
      }`}
      onMouseDown={handleMouseDown}
      style={{
        minWidth: '4px',
        maxWidth: '8px',
        margin: '0 -2px',
        borderRadius: '4px',
        zIndex: 10,
      }}
    >
      <div className="flex flex-col gap-1.5 p-0.5">
        <div className="w-0.5 h-3 rounded-full" style={{ backgroundColor: isDragging ? '#fff' : '#54657e' }} />
        <div className="w-0.5 h-3 rounded-full" style={{ backgroundColor: isDragging ? '#fff' : '#54657e' }} />
        <div className="w-0.5 h-3 rounded-full" style={{ backgroundColor: isDragging ? '#fff' : '#54657e' }} />
      </div>
    </div>
  );
}