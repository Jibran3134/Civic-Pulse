import React from 'react'
import { AlertTriangle, ShieldAlert, Info } from 'lucide-react'
import { Priority } from '../types'

interface PriorityBadgeProps {
  priority: Priority
}

export const PriorityBadge: React.FC<PriorityBadgeProps> = ({ priority }) => {
  const getIcon = () => {
    switch (priority) {
      case 'high':
        return <ShieldAlert size={12} />
      case 'normal':
        return <AlertTriangle size={12} />
      case 'low':
        return <Info size={12} />
      default:
        return null
    }
  }

  return (
    <span className={`badge badge-priority badge-${priority}`}>
      {getIcon()}
      <span>{priority.toUpperCase()}</span>
    </span>
  )
}
