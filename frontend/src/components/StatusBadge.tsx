import React from 'react'
import { CheckCircle2, Clock, XCircle, AlertCircle } from 'lucide-react'
import { Status } from '../types'

interface StatusBadgeProps {
  status: Status
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const getIcon = () => {
    switch (status) {
      case 'open':
        return <AlertCircle size={12} />
      case 'in_progress':
        return <Clock size={12} />
      case 'resolved':
        return <CheckCircle2 size={12} />
      case 'rejected':
        return <XCircle size={12} />
      default:
        return null
    }
  }

  const getLabel = () => {
    switch (status) {
      case 'open':
        return 'Open'
      case 'in_progress':
        return 'In Progress'
      case 'resolved':
        return 'Resolved'
      case 'rejected':
        return 'Rejected'
      default:
        return status
    }
  }

  return (
    <span className={`badge badge-status badge-${status}`}>
      {getIcon()}
      <span>{getLabel()}</span>
    </span>
  )
}
